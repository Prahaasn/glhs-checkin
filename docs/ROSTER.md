# Official staff roster import

Source: [Green Level High School Faculty & Staff Directory](https://greenlevelhs.wcpss.net/our-school/faculty-staff-directory), verified September 26, 2026. The site lists 141 constituents in 16 pages, including classroom teachers, administration, counselors, and support staff. This is a public-directory snapshot, not proof of current employment or presence.

`app.roster fetch-directory` checks school identity, directory element identity, contiguous page ranges, a stable advertised total, and unique directory IDs before writing a manifest. Finalsite page links alone return page one; the fetcher follows the element endpoint used by the site's own pagination and its cache-busting behavior. Any missing page, changed count, duplicate ID, wrong school, unsafe pagination URL, or unexpected structure aborts the fetch. No partial roster replaces a successful manifest.

The local verified dataset was independently read through all 16 pages in the in-app browser and through the HTTP fetcher; all 141 directory IDs and normalized names matched. The final page was 136–141 (six entries). Roster files, source downloads, database files, session tokens, and badge tokens stay outside Git in ignored data/.

Import validates the entire manifest first, then runs one transaction. Dry-run rolls it back. Re-import skips an identical existing directory ID/name without rotating badges or changing attendance. A mismatched existing ID/name aborts for office review. People missing from a later directory are not silently deactivated. Office staff must reconcile the snapshot with the school's authoritative staff list.

Imported IDs use `DIR-<public-directory-id>` and are provisional app identifiers, not employee ID numbers. Imported staff have no scan history and display **Not recorded**. Their initial badge hashes have no issued token; use Teachers & badges → Replace badge to explicitly issue and print a card. The import does not save a printable token for every person.

Local commands:

```sh
uv run python -m app.roster fetch-directory
uv run --env-file .env python -m app.roster import-directory --dry-run
uv run --env-file .env python -m app.roster import-directory
```

The supervised school roster is in `data/school.db`; the original fictional demo remains separately preserved in `data/checkin.db`. `.env` selects the active database. Do not copy attendance or badge files into the public repository.
