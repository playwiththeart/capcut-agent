"""4단: 잔말(filler) + NG/재촬영(반복 테이크) 감지.

★ 전체 대본으로 판단(단어 단위 X). 같은 대사를 여러 번 찍은 반복 테이크는 마지막 것만
남기고 앞의 것들을 컷, 그 자체로 의미 없는 순수 잔말은 제거한다.
감지만 하고(어떤 세그먼트를 버릴지), 실제 컷/타임라인 반영은 파이프라인이 담당.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, List

# 그 자체로 한 세그먼트일 때만 컷하는 순수 잔말(맥락상 실제 단어일 수 있어 보수적으로)
FILLERS = {
    "음", "어", "그", "아", "흠", "에", "엇", "으", "윽",
    "음음", "어어", "그그", "아아", "어우", "에이", "그니까", "뭐랄까",
}


def _norm(text: str) -> str:
    """공백·문장부호 제거한 비교용 문자열."""
    return re.sub(r"[\s.,!?…·\"'~\-()\[\]]+", "", text)


def is_filler(text: str) -> bool:
    n = _norm(text)
    if not n:
        return True
    if n in FILLERS:
        return True
    # 2글자 이하이면서 전부 잔말 음절
    return len(n) <= 2 and all(c in "음어그아흠에으윽" for c in n)


def _same_take(a: str, b: str, threshold: float = 0.75) -> bool:
    """a, b가 같은 대사의 반복 테이크인지. threshold↓ = 더 공격적."""
    na, nb = _norm(a), _norm(b)
    if len(na) < 4 or len(nb) < 4:
        return False
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    # 테이크가 점점 완성되는 경우: 짧은 쪽이 긴 쪽의 접두(충분히 길 때만)
    if len(short) >= 4 and long.startswith(short):
        return True
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def detect_ng(
    segments: List[Dict],
    threshold: float = 0.75,
    cut_filler: bool = True,
) -> Dict[str, List[int]]:
    """컷 대상 세그먼트 인덱스를 분류해 반환 (마지막 테이크를 남김).

    returns {"filler": [...], "retake": [...]}  (둘 다 컷 대상)
    """
    filler = [i for i, s in enumerate(segments) if is_filler(s.get("text", ""))] if cut_filler else []
    filler_set = set(filler)

    retake: List[int] = []
    prev = None  # 직전에 남긴 '내용' 세그먼트 인덱스
    for i, s in enumerate(segments):
        if i in filler_set:
            continue
        if prev is not None and _same_take(segments[prev]["text"], s["text"], threshold):
            retake.append(prev)   # 이전 테이크는 NG → 컷, 현재(더 최신)를 남김
        prev = i

    return {"filler": filler, "retake": sorted(set(retake))}


def ng_ranges(segments: List[Dict], threshold: float = 0.75, cut_filler: bool = True):
    """컷할 (start, end) 원본 시간 구간 목록 + 분류 카운트."""
    cats = detect_ng(segments, threshold, cut_filler)
    idx = sorted(set(cats["filler"]) | set(cats["retake"]))
    ranges = [(float(segments[i]["start"]), float(segments[i]["end"])) for i in idx]
    return ranges, {"filler": len(cats["filler"]), "retake": len(cats["retake"])}


def subtract_ranges(keeps, remove, min_keep: float = 0.15):
    """keeps 구간들에서 remove 구간(NG/잔말)을 도려낸다. 둘 다 (s,e) 초 단위."""
    remove = sorted(remove)
    result = []
    for ks, ke in keeps:
        pieces = [(ks, ke)]
        for rs, re_ in remove:
            nxt = []
            for s, e in pieces:
                if re_ <= s or rs >= e:      # 겹치지 않음
                    nxt.append((s, e))
                else:                         # 겹침 → 앞/뒤 조각만 남김
                    if s < rs:
                        nxt.append((s, rs))
                    if re_ < e:
                        nxt.append((re_, e))
            pieces = nxt
        result.extend(pieces)
    return [(s, e) for s, e in result if e - s >= min_keep]
