# response_agent.py / base.py 팀 통합 제안

## 1. 배경

D파트는 이번 스프린트에서 그래프 노드 10~13(`stage_router`/`risk_trigger`/`victim_check`/`special_cases`)과 `graph.py` 배선까지 마치고, 실제 GPT-4o 라이브 호출 검증까지 끝냈습니다. 이 과정에서 팀 공용 파일 2개를 계속 우회해왔습니다:

- **`app/llm/base.py`** — `call_llm_stream_raw(prompt) -> AsyncGenerator[str, None]`가 `raise NotImplementedError` 스텁 상태였고, "팀 전체가 원칙적으로 안 건드리는 파일"로 문서화돼 있었습니다. 진행이 막혀서 D파트가 자체 OpenAI 클라이언트를 만들어 대체했습니다.
- **`app/graph/agents/response_agent.py`** — `generate_response_stream(part: str, judgement: dict, retrieved: dict)`가 마찬가지로 스텁 상태였고, `part` 인자를 받는 걸 보면 파트 공통(unit 14 "응답 공통 템플릿 4원칙")으로 설계된 게 명백합니다. D파트가 `response_assembly.py`로 자체 우회했습니다.

두 우회 모두 "지금 당장 막힌 걸 풀고, 통합 시점에 팀과 공유"를 전제로 진행했습니다. 이 문서가 그 공유입니다 — **코드는 건드리지 않았고, 실제 반영 여부/방식은 팀 논의로 결정해주세요.**

## 2. D파트가 실제로 구현한 것

### 2.1 `llm/d_part.py` — base.py 대체
```python
MODEL = "gpt-4o"
MAX_RETRIES = 3
_client = AsyncOpenAI(api_key=settings.openai_api_key)

async def _call_llm(prompt: str) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            stream = await _client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            return "".join([event.choices[0].delta.content or "" async for event in stream])
        except (RateLimitError, APIError):
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(2**attempt)
```
구조화된 값(JSON)이 필요한 4개 판별 노드는 스트림을 전부 모아 `json.loads`로 파싱합니다. 최종 사용자 응답처럼 진짜 토큰 단위 스트리밍이 필요한 경우엔 별도 함수(`generate_response`, 아래 2.2)를 씁니다.

재시도 패턴은 `rag/embeddings/base.py`(팀이 이미 구현해둔 임베딩 호출 재시도)를 그대로 참고해 복제했습니다 — `MAX_RETRIES`/exponential backoff 구조가 동일합니다.

### 2.2 `response_assembly.py` — response_agent.py 대체

핵심 설계 통찰: **실제로 "원문→해설→상황적용" 조립이 필요한 경로는 victim_check가 최종판단(높음/추가확인)을 확정하는 경우 하나뿐입니다.** 나머지 종결 경로(스테이지 확인질문, victim_check 후속질문/fallback, special_cases 안내문)는 이미 완결된 텍스트를 갖고 있어 조립이 불필요합니다. 이 덕분에 우회 구현이 훨씬 작아졌습니다:

```python
async def generate_response(context: str) -> AsyncGenerator[str, None]:
    prompt = _render_prompt("response", context=context)  # graph/parts/d_part/prompts/response.md
    stream = await _client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    async for event in stream:
        content = event.choices[0].delta.content
        if content:
            yield content
```
`response_assembly.py`가 `DPartRetriever.search_by_requirement()`로 RAG 검색 후 판단결과+슬롯+검색결과를 평문 컨텍스트로 조립해 이 함수에 넘깁니다. 프롬프트는 `graph/parts/d_part/prompts/response.md`에 이미 초안이 있었고(원문/해설/상황적용/면책조항 4단 구조), 그대로 재사용했습니다.

## 3. 팀에 공유할 발견사항 3가지

### 3.1 GPT-4o가 JSON을 마크다운 코드펜스로 감싸서 응답함
JSON만 반환하라고 프롬프트에 명시해도, 실제 라이브 호출에서 GPT-4o가 다음처럼 응답하는 경우가 있었습니다:
```
```json
{"stage": "전"}
```
```
`json.loads()`가 그대로는 파싱 실패합니다. D파트는 `llm/d_part.py`에 아래 헬퍼를 추가해 처리했습니다:
```python
def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text.removeprefix("```")
        text = text.removesuffix("```").strip()
    return text
```
**제안**: `base.py`가 실제로 구현될 때 이 처리를 공통으로 넣어두면 모든 파트가 각자 겪지 않아도 됩니다. mock/monkeypatch 테스트로는 이 문제를 절대 잡을 수 없었다는 점도 참고하세요 — 실제 라이브 호출 검증이 필요한 이유입니다.

### 3.2 LangGraph `ainvoke()` 반환 dict는 노드가 받은 state와 동일 객체가 아님
스트리밍 응답을 그래프 상태에 담아 내보내는 파트가 있다면 겪을 수 있는 함정입니다. D파트는 최초에 "스트림을 소진한 뒤 그 전체 텍스트를 `state["final_answer"]`에 채워 넣는" 방식을 시도했는데, `graph.ainvoke()`가 반환하는 dict는 노드 함수가 다뤘던 dict와 **다른 객체**라서 이 사후 변경이 호출부에 전혀 반영되지 않았습니다(직접 `id()` 비교로 확인). 결국 스트림을 소비하는 쪽(라우트 파일)이 청크를 직접 모아 전체 텍스트를 재구성하는 방식으로 수정했습니다. 종단 스모크 테스트를 작성하는 과정에서 발견했고, 노드별 단위 테스트만으로는 못 잡는 종류의 버그였습니다.

### 3.3 재시도 패턴 재사용 가능
`rag/embeddings/base.py`의 `MAX_RETRIES`+exponential backoff 패턴이 이미 팀 컨벤션으로 자리잡혀 있어서, `base.py`를 실제로 구현할 때도 그대로 복제 가능합니다(위 2.1 코드가 실제 예시).

## 4. `response_agent.py` 실제 구현 제안

시그니처(`generate_response_stream(part, judgement, retrieved)`)를 파트 무관하게 만들려면, D파트가 이미 쓰고 있는 `graph/parts/{part}/prompts/response.md` 컨벤션을 그대로 활용할 수 있습니다 — 각 파트가 자기 프롬프트 파일만 준비하면 `response_agent.py` 본체는 `part` 값으로 해당 경로를 찾아 프롬프트를 로드하고, `judgement`/`retrieved`를 평문 컨텍스트로 조립해 스트리밍 호출하는 로직 하나로 통일 가능합니다(D파트의 `_format_context`/`generate_response`가 사실상 이 일반화의 예시 구현입니다).

미정 사항: `judgement`/`retrieved`의 정확한 dict 스키마가 파트마다 다를 수 있어(D파트는 `victim_slots`+`victim_judgment`, 다른 파트는 다른 판단 구조일 수 있음) 공통 포맷을 팀이 먼저 정해야 합니다.

## 5. `base.py` 실제 구현 제안

위 2.1의 `_call_llm`을 그대로 `call_llm_stream_raw`에 옮기는 수준이면 됩니다. 다만 원래 시그니처(`AsyncGenerator[str, None]`, 스트리밍 전용)와 D파트가 실제로 쓰는 두 가지 소비 패턴(① 스트림을 모아 JSON 파싱, ② 스트림 그대로 전달)이 다르므로, `base.py`는 순수 스트리밍만 제공하고 "모아서 파싱"은 각 파트(`llm/{part}.py`) 책임으로 남기는 게 원래 설계 의도에 맞습니다(3.1의 코드펜스 처리는 파싱을 하는 쪽 — 즉 각 파트 또는 공통 파싱 헬퍼 — 에서 처리).

## 6. 팀 논의 필요 사항

- `base.py`/`response_agent.py`의 실제 담당자가 누구인지 (지금까지 아무도 안 채운 상태로 확인됨)
- 다른 파트(A/B/C)도 이 두 파일이 막혀서 비슷한 우회를 했는지 — 우회 방식이 파트마다 다르면 나중에 통합이 더 어려워짐
- 코드펜스 파싱(3.1)을 `base.py` 레벨에서 공통 처리할지, 각 파트가 알아서 처리할지
- `response_agent.py`의 `judgement`/`retrieved` 공통 스키마를 정할지, 아니면 파트별로 자유롭게 둘지
