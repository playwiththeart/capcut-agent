"""대본(컷된 결과 타임라인) → 짧은 자막 청크.

★ 공백편집 > 자동자막: 무음을 제거한 컷 오디오에 ASR을 돌리므로, 대본 타임스탬프는
이미 출력(잘린) 타임라인이다. 따라서 원본→출력 매핑이 필요 없고, 컷 경계에서 자연히 끊긴다.
여기서는 긴 문장을 짧은 자막으로 쪼개고(단어 단위, 의존명사 보호) 겹치지 않게 정리한다.
"""
from __future__ import annotations

from typing import Dict, List

# 의존명사: 단독으로 줄 첫머리에 오면 어색해서 새 청크 시작 단어로 두지 않는다(앞 청크에 붙임)
_DEP_NOUNS = ("거", "것", "수", "때", "줄", "데", "뿐", "채", "척", "만큼", "듯")


def _emit_chunk(words: List[Dict]) -> Dict:
    return {
        "start": float(words[0]["start"]),
        "end": float(words[-1]["end"]),
        "text": " ".join(w["word"].strip() for w in words if (w.get("word") or "").strip()),
    }


def chunk_segment(seg: Dict, max_chars: int) -> List[Dict]:
    """긴 세그먼트를 단어 타임스탬프 기준으로 max_chars 이하 청크로 쪼갠다.

    의존명사(거/것/수/때…)로 새 청크가 시작되지 않게 앞 청크에 붙여 어색함을 막는다.
    """
    words = seg.get("words") or []
    text = seg.get("text", "")
    if not words or len(text) <= max_chars:
        return [{"start": float(seg["start"]), "end": float(seg["end"]), "text": text}]

    chunks: List[Dict] = []
    cur: List[Dict] = []
    cur_len = 0
    for w in words:
        wt = (w.get("word") or "").strip()
        if not wt:
            continue
        add = len(wt) + (1 if cur else 0)
        if cur and cur_len + add > max_chars and not wt.startswith(_DEP_NOUNS):
            chunks.append(_emit_chunk(cur))
            cur, cur_len = [w], len(wt)
        else:
            cur.append(w)
            cur_len += add
    if cur:
        chunks.append(_emit_chunk(cur))
    return chunks


def subtitles_from_transcript(
    transcript: Dict,
    total_out: float,
    min_dur: float = 0.3,
    max_chars: int = 999,
) -> List[Dict]:
    """컷-타임 대본을 자막 [{start,end,text}]로 변환(초 단위).

    - 세그먼트가 max_chars보다 길면 단어 단위로 쪼갠다(짧은 자막)
    - 너무 짧은 자막은 min_dur까지 늘려 가독 확보
    - 같은 텍스트 트랙이므로 인접 자막이 겹치지 않게 끝을 다음 시작으로 클램프
    """
    subs: List[Dict] = []
    for s in transcript.get("segments", []):
        for chunk in chunk_segment(s, max_chars):
            if not chunk["text"]:
                continue
            o_s = max(0.0, float(chunk["start"]))
            o_e = min(total_out, float(chunk["end"]))
            if o_e - o_s < min_dur:
                o_e = min(total_out, o_s + min_dur)
            if o_e <= o_s:
                continue
            subs.append({"start": o_s, "end": o_e, "text": chunk["text"]})

    subs.sort(key=lambda x: x["start"])
    for i in range(len(subs) - 1):
        if subs[i]["end"] > subs[i + 1]["start"]:
            subs[i]["end"] = subs[i + 1]["start"]
    return [x for x in subs if x["end"] - x["start"] > 1e-3]
