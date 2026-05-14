"""Mini LLM-классификаторы намерений.

Используются как fallback после быстрых regex-парсеров. Один маленький
JSON-вызов без tools — гораздо надёжнее чем надеяться что главный LLM-pass
с десятками правил сам поймёт что владелец хотел изменить статус.
"""

import json

from core import LLM_MODEL, llm, log


STATUS_INTENT_SYSTEM = """ты — fast intent classifier для personal assistant.

задача: определить является ли сообщение владельца установкой ТЕКУЩЕГО СТАТУСА.
статус = «где я сейчас / что я сейчас делаю / когда я недоступен».

верни СТРОГО JSON, без markdown:
{
  "is_status": true | false,
  "status_text": "если true — КОРОТКИЙ текст для status (без 'я ', начинать с глагола или предлога). иначе null",
  "hours": число или null,
  "days": число или null,
  "scopes": массив строк или null
}

is_status=true когда:
- «я в [месте]»: «я в лесу», «я в другом городе», «я в москве», «я на даче»
- «уехал/ушел/пошел/улетел/еду/лечу куда-то»: «уехал в командировку», «улетел в париж», «пошел гулять»
- «я в [состояние]»: «в отпуске», «занят», «в дороге», «у врача», «на встрече»
- «сплю/лежу/отдыхаю/спать» в смысле статуса
- «если что говори всем что я X», «передавай что я Y» — это тоже статус
- «нет связи N часов», «недоступен N дней», «не пиши пока»

is_status=false когда:
- обычный разговор: «привет», «как дела», «что нового», «спасибо»
- запросы: «напомни», «запомни», «что у меня по задачам», «новости», «найди»
- факты о других: «артём мой партнёр», «маша из питера»
- общие вопросы / просьбы: «как настроить», «что ты умеешь»
- эмоции/реакции: «ок», «спасибо», «👍», «лол»

длительность (КРИТИЧНО — не выдумывай):
- hours/days передавай ТОЛЬКО если владелец явно назвал срок:
  - «на 3 часа» → hours=3
  - «на неделю» → days=7
  - «на месяц» → days=30
  - «до вечера», «до утра» → hours=4
- если срок НЕ назван — оба null. НЕ предполагай «по умолчанию час».

scopes — только если явно: «скажи коллегам» → ['work'], «семье» → ['family'], «только девушке» → ['girlfriend'], «боссу» → ['work'].

если сомневаешься — is_status=false. лучше пропустить чем сломать обычный разговор."""


async def classify_status_intent(text: str) -> dict | None:
    """Single-purpose классификатор статусных намерений.

    Возвращает dict с полями {is_status, status_text, hours, days, scopes}
    или None если LLM упал. is_status=False означает что обычный разговор.
    """
    try:
        resp = await llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": STATUS_INTENT_SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("status classifier returned non-json")
        return None
    except Exception:
        log.exception("status classifier failed")
        return None
