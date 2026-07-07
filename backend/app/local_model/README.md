# local_model — 팀 공통 로컬 모델 실험 공간

GPT-4o 기반 파이프라인과는 별도로 각 파트가 자유롭게 로컬 모델을 실험하는 공간입니다.
기존 파이프라인(graph/llm/rag)에서 import되지 않는 한 안전하게 실험할 수 있습니다.

## 현재 실험 현황
- `models/d_part/` — 위험신호 감지(risk_trigger) 경량 분류기, 등기부등본 OCR 검토 (D파트 담당)
- `models/common/` — 대화 요약용 Ollama 기반 로컬 모델 검토 (한국어 성능 + 경량 모델 후보 조사 중)
- `models/a_part/`, `models/b_part/`, `models/c_part/` — 아직 실험 없음 (자리만 확보)

## 연결 방법
방향이 정해지면 각 `interface.py`를 기존 코드에서 한 줄로 연결합니다.

```python
from app.local_model.models.d_part.interface import predict
```
