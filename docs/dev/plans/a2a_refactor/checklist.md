# Чек-лист приёмки

Отмечать по мере выполнения. Пункт считается закрытым, только если проверен
командой, а не рассуждением.

## Инварианты (проверять на каждом коммите)

- [ ] `git diff main --stat blocksnet_agent/agent.py` — пусто
- [ ] `git diff main --stat blocksnet_agent/hypotheses.py blocksnet_agent/metrics.py` — пусто
- [ ] `git diff main --stat blocksnet_agent/tools/registry.py` — пусто
- [ ] Существующие тесты из `baseline.txt` не покраснели
- [ ] Нигде не захардкожено число инструментов (`grep -rn "== 3[23]" tests/`)
- [ ] Текст, возвращаемый инструментами, не изменён
- [ ] Внутри `blocksnet_agent/` нет MCP-клиента (`grep -rn "mcp" blocksnet_agent/ --include=*.py`)

## По шагам

**00 Preflight**
- [ ] venv поднят, зависимости стоят
- [ ] `baseline.txt`, `tools_snapshot.txt` зафиксированы
- [ ] `spike-a2a.md` написан, версия `a2a-sdk` запинена
- [ ] `pyproject.toml` с extras создан

**01 Каталог**
- [ ] `tools/catalog.py` создан, `registry.py` цел
- [ ] `test_tool_catalog.py` зелёный
- [ ] `submit_answer` в blocklist; `find_tools`/`get_tool_help` в каталоге

**02 Сессии**
- [ ] `blocksnet_mcp/session.py` создан, без импортов из `blocksnet_agent`
- [ ] TTL, LRU, изоляция, потокобезопасность покрыты тестами
- [ ] `close()` очищает `state`

**03 MCP-сервер**
- [ ] `CHAT_URL= API_KEY= python -m blocksnet_mcp` — стартует
- [ ] `tools/list` отдаёт весь каталог + служебные, `submit_answer` отсутствует
- [ ] `session_id` присутствует в схеме входа каждого инструмента
- [ ] Изоляция сессий подтверждена через `list_cached_data`
- [ ] `test_tool_contract.py`, `test_async_mcp_contract.py` зелёные **без правок**
- [ ] `scripts/smoke_mcp_tools.py` проходит
- [ ] Исключение инструмента → конверт `failed`, не транспортная ошибка

**04 Агент**
- [ ] Отмена одной задачи не останавливает другие (тест)
- [ ] `stop_run(all_runs=True)` работает
- [ ] Сигнатуры runtime обратно совместимы

**05 A2A**
- [ ] `python -m blocksnet_agent` поднимается
- [ ] Agent Card валиден, два skill
- [ ] `analyze_urban_question` (A2A) даёт тот же набор ключей, что MCP-tool
- [ ] `run_pipeline` эмитит ≥2 статусных события
- [ ] Дедлайн → `partial`, не `failed`
- [ ] Лимит конкурентности соблюдается

**06 Auth и контекст**
- [ ] `AUTH_ENABLED=false` → поведение как раньше
- [ ] 401/403 корректны, сообщения не различают «нет токена»/«неверный»
- [ ] Path traversal (`../`, `\x00`, `a/b`) отклоняется — тесты есть
- [ ] Токены не попадают в логи и в `outputs/mcp_trace.log`

**07 Docker**
- [ ] Оба образа собираются, `docker compose up` — `healthy`
- [ ] MCP-контейнер стартует без LLM-переменных
- [ ] `langgraph`/`langchain_openai`/`tiktoken` не импортируются в MCP (тест)
- [ ] `data/` не попал в образ

**08 Документация**
- [ ] `mcp_tool_catalog.md` сгенерирован, тест на актуальность зелёный
- [ ] `tool_contract.md` содержит v1 и v2
- [ ] `a2a_agent_card.md` с реальным выводом
- [ ] README, architecture, deployment, WIKI-LLM обновлены
- [ ] Таблица переменных окружения полна
- [ ] Все markdown-ссылки живые
- [ ] Отчёт о завершении написан

## Финальная проверка

```bash
python -m pytest -q                       # не хуже baseline + новые зелёные
python scripts/smoke_mcp_tools.py         # ok
python scripts/smoke_a2a_agent.py         # ok (нужен LLM-конфиг)
bash scripts/smoke_docker.sh              # ok
```

- [ ] Прогон на реальном вопросе через A2A даёт ответ, эквивалентный
      прогону через текущий MCP-tool на `main` — **сравнить**
      `recommendation_blocks`, `confidence`, число гипотез. Это главная
      защита от тихого регресса из-за `state` (см.
      [../../deferred/a2a_refactor_deferred.md](../../deferred/a2a_refactor_deferred.md) D1).
- [ ] `deviations.md` пуст или все отклонения объяснены
- [ ] PR описывает: что изменилось для потребителей, что deprecated,
      что отложено
