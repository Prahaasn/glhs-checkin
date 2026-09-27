import pytest
from app.roster import SOURCE_URL, fetch_directory
from app.security import FailureLimiter
from fastapi import HTTPException


def page(first,last,total,ids,next_page=None):
    items=''.join(f'<div class="fsConstituentItem" data-constituent-id="{i}"><h3><a class="fsConstituentProfileLink">Example Staff {i}</a></h3><div class="fsTitles">Teacher</div></div>' for i in ids)
    next_link=f'<a class="fsNextPageLink" href="{next_page}">next</a>' if next_page else ''
    return f'<body data-pageid="1"><div class="fsDirectory" id="fsEl_123"><title>Faculty Directory - Green Level High School</title><span class="fsPaginationLabel">showing {first} - {last} of {total} constituents</span>{items}{next_link}</div></body>'


def test_fetch_walks_all_pages_and_checks_count():
    first=page(1,2,3,[1,2],'?const_page=2');second=page(3,3,3,[3])
    result=fetch_directory(lambda url:first if url==SOURCE_URL else second)
    assert result['expected_total']==3 and result['pages']==2
    assert [r['directory_id'] for r in result['staff']]==['1','2','3']
    assert result['staff'][0]['role']=='Teacher'


@pytest.mark.parametrize('html',[
    page(1,2,3,[1,2]),
    page(1,2,2,[1,1]),
    page(1,2,2,[1]),
    page(1,1,2,[1],'https://evil.example/'),
    page(1,1,2,[1],SOURCE_URL),
    page(1,1,1,[1]).replace('Green Level','Green Hope'),
])
def test_fetch_rejects_incomplete_duplicate_wrong_school_or_unsafe_pages(html):
    with pytest.raises(ValueError):
        fetch_directory(lambda _:html)


def test_limiter_expires_and_does_not_grow_without_bound():
    now=[0];limiter=FailureLimiter(limit=2,clock=lambda:now[0])
    limiter.failed('one');limiter.failed('one')
    with pytest.raises(HTTPException):limiter.check('one')
    now[0]=61;limiter.check('one')
    for i in range(10001):limiter.failed(str(i))
    assert len(limiter.entries)==10000
