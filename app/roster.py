"""Fetch only the official public directory; roster files remain outside Git."""
import argparse
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.main import TeacherInput, badge_hash, create_app
from app.models import Base, Teacher

SOURCE_URL = 'https://greenlevelhs.wcpss.net/our-school/faculty-staff-directory'


class DirectoryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current = None
        self.depth = 0
        self.capture = None
        self.title_depth = None
        self.pagination = False
        self.pagination_text = ''
        self.next_page = None
        self.in_title = False
        self.page_title = ''
        self.element_id = None
        self.page_id = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'body':
            self.page_id = attrs.get('data-pageid')
        if tag == 'div' and 'fsDirectory' in classes:
            self.element_id = attrs.get('id', '').removeprefix('fsEl_')
        if tag == 'title':
            self.in_title = True
        if tag == 'span' and 'fsPaginationLabel' in classes:
            self.pagination = True
        if tag == 'a' and 'fsNextPageLink' in classes:
            self.next_page = attrs['href']
        if tag == 'div':
            if self.current is not None:
                self.depth += 1
            elif 'fsConstituentItem' in classes:
                self.current = {'directory_id': attrs['data-constituent-id'], 'name': '', 'role': ''}
                self.depth = 1
            if self.current is not None and 'fsTitles' in classes:
                self.capture = 'role'
                self.title_depth = self.depth
        if self.current is not None and tag == 'a' and 'fsConstituentProfileLink' in classes:
            self.capture = 'name'

    def handle_data(self, data):
        if self.in_title:
            self.page_title += data
        if self.pagination:
            self.pagination_text += data
        if self.current is not None and self.capture:
            self.current[self.capture] += data

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if tag == 'span':
            self.pagination = False
        if self.current is not None:
            if tag == 'a' and self.capture == 'name':
                self.capture = None
            if tag == 'div':
                if self.depth == self.title_depth:
                    self.capture = None
                    self.title_depth = None
                self.depth -= 1
                if self.depth == 0:
                    self.current['name'] = ' '.join(self.current['name'].split())
                    self.current['role'] = ' '.join(self.current['role'].split())
                    self.rows.append(self.current)
                    self.current = None

    def bounds(self, require_school=True):
        match = re.search(r'showing\s+(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\s+constituents', self.pagination_text)
        if not match or (require_school and 'Green Level High School' not in self.page_title):
            raise ValueError('Directory structure or school identity could not be verified.')
        return tuple(map(int, match.groups()))


def fetch_directory(fetch=None):
    def download(url):
        with urlopen(Request(url, headers={'User-Agent': 'GLHS-local-roster-pilot/0.1'}), timeout=20) as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme != 'https' or final_url.netloc != 'greenlevelhs.wcpss.net':
                raise ValueError('Directory download redirected outside the official school site.')
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError('Directory page exceeded the size limit.')
            return data.decode('utf-8')
    fetch = fetch or download
    url, seen, rows, expected, covered = SOURCE_URL, set(), [], None, 0
    element_id = page_id = None
    while url:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != 'greenlevelhs.wcpss.net' or parsed.path not in (urlparse(SOURCE_URL).path, '/fs/elements/'+str(element_id)):
            raise ValueError('Directory pagination left the official school directory.')
        if url in seen or len(seen) >= 100:
            raise ValueError('Directory pagination loop detected.')
        seen.add(url)
        page = DirectoryParser()
        page.feed(fetch(url))
        first, last, total = page.bounds(require_school=len(seen)==1)
        if len(seen)==1:
            element_id, page_id = page.element_id, page.page_id
            if not element_id or not element_id.isdigit() or not page_id or not page_id.isdigit():
                raise ValueError('Official directory element identity is missing.')
        elif page.element_id != element_id:
            raise ValueError('Directory element identity changed during pagination.')
        if expected is None:
            expected = total
        if total != expected or first != covered + 1 or len(page.rows) != last - first + 1:
            raise ValueError('Directory changed or a page is incomplete; no roster imported.')
        rows.extend(page.rows)
        covered = last
        if page.next_page:
            link = urlparse(urljoin(SOURCE_URL, page.next_page))
            if link.scheme != 'https' or link.netloc != 'greenlevelhs.wcpss.net' or link.path != urlparse(SOURCE_URL).path:
                raise ValueError('Directory pagination left the official school directory.')
            next_number = parse_qs(link.query).get('const_page', [''])[0]
            if not next_number.isdigit() or int(next_number) != len(seen)+1:
                raise ValueError('Directory pagination is not sequential.')
            # Finalsite's own pagination loads this element endpoint; page URLs return page one.
            query = urlencode({'const_page': next_number, 'is_draft': 'false', 'is_load_more': 'true', 'page_id': page_id, 'parent_id': element_id, '_': str(int(time.time()*1000))})
            url = 'https://greenlevelhs.wcpss.net/fs/elements/'+element_id+'?'+query
        else:
            url = None
    if not rows or len(rows) != expected or len({r['directory_id'] for r in rows}) != expected:
        raise ValueError('Roster count or unique directory IDs do not match the official total.')
    return {'source_url': SOURCE_URL, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'expected_total': expected, 'pages': len(seen), 'staff': rows}


def import_directory(engine, manifest, dry_run=False):
    rows = manifest.get('staff', [])
    if manifest.get('source_url') != SOURCE_URL or len(rows) != manifest.get('expected_total') or not rows:
        raise ValueError('Roster source or expected count is invalid.')
    validated = []
    ids = set()
    for row in rows:
        directory_id = str(row.get('directory_id', ''))
        if not re.fullmatch(r'\d{1,12}', directory_id) or directory_id in ids:
            raise ValueError('Roster has an invalid or duplicate directory ID.')
        ids.add(directory_id)
        validated.append(TeacherInput(teacher_id='DIR-'+directory_id, name=row['name']))
    if engine.dialect.name == 'sqlite':
        Base.metadata.create_all(engine)
    with Session(engine) as session:
        if engine.dialect.name == 'sqlite':
            session.execute(text('BEGIN IMMEDIATE'))
        added = skipped = 0
        for row in validated:
            existing = session.scalar(select(Teacher).where(Teacher.teacher_id == row.teacher_id).with_for_update())
            if existing:
                if existing.name != row.name:
                    raise ValueError('Existing directory ID has a different name; office review required.')
                skipped += 1
                continue
            # Imported names have no usable badge until the office explicitly issues one.
            session.add(Teacher(teacher_id=row.teacher_id, name=row.name, badge_hash=badge_hash(secrets.token_urlsafe(32))))
            added += 1
        if dry_run:
            session.rollback()
        else:
            session.commit()
    return {'added': added, 'skipped': skipped, 'dry_run': dry_run}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['fetch-directory', 'import-directory'])
    parser.add_argument('--file', default='data/directory/roster.json')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.command == 'fetch-directory':
        manifest = fetch_directory()
        path = Path(args.file)
        if '.git' in path.parts or not path.resolve().is_relative_to((Path.cwd() / 'data').resolve()):
            raise SystemExit('Save directory data only inside ignored data/.')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as file:
            json.dump(manifest, file, indent=2)
        temporary.replace(path)
        print(f"Verified {manifest['expected_total']} unique staff across {manifest['pages']} pages; saved locally.")
    else:
        manifest = json.loads(Path(args.file).read_text())
        result = import_directory(create_app().state.engine, manifest, args.dry_run)
        print(json.dumps(result))


if __name__ == '__main__':
    main()
