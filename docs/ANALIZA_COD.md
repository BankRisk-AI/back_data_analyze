# Analiza codului `eba_analyst` (ce am citit, ce am rulat, ce am găsit)

Am citit toate fișierele din `app/`, `tests/`, `main.py`, `Makefile`, `requirements.txt`, `architecture.txt` și `README.md` și am rulat cele 25 de teste ale tale într-un PostgreSQL 16 din mediul meu (fișierul `.env` l-am pus deoparte și nu i-am afișat valorile). **Toate cele 25 trec**, inclusiv testul pe fișierele reale din 2020.

## Ce este bine făcut
- Straturile `domain` / `application` / `infrastructure` / `presentation` sunt respectate la nivel de directoare, iar `domain` nu importă nimic din web sau din baza de date.
- Workerul este generic: registru de handlere pe tipul jobului, `FOR UPDATE SKIP LOCKED`, stări `pending`, `processing`, `completed`, `failed`, progres și mesaj.
- Erorile sunt `problem+json`, cu tipuri stabile; testele folosesc o bază de date separată, creată și ștearsă de `conftest.py`.
- Decizia de a face API-ul asincron (încărcare rapidă, citirea fișierelor în worker) este corectă pentru fișiere de 65 MB.

## Probleme găsite

| # | Gravitate | Unde | Problema | Ce propun |
|---|---|---|---|---|
| 1 | Blocantă | `main.py` | Conține o comandă shell lipită (`cat > app/core/database/schema_manager.py <<'PY' ...`), nu cod Python; `uvicorn main:app` nu poate porni | Punct de intrare ASGI real: `from app.main import app_from_env` |
| 2 | Importantă | `requirements.txt` | Lipsește `python-dotenv`, importat în `settings.py` și `conftest.py`; funcționează la tine doar fiindcă `.venv` îl are | Adaugă `python-dotenv` (și `pyyaml` pentru OpenAPI) |
| 3 | Importantă | `application/ingest_service.py` (313 rânduri) | Amestecă încărcarea, înregistrarea, inspectarea conținutului, încărcarea în staging, raportul pe perioade, interogările și inițializarea schemei; `enqueue_import` repetă codul de stocare, verificare de duplicate și înregistrare din `ingest` | Împărțit în `upload_service`, `staging_service`, `queries` |
| 4 | Importantă | `application/*` | SQL direct în stratul de aplicare; în `infrastructure/database` există doar un predicat | Funcții de depozit (`repositories.py`) care primesc un cursor |
| 5 | Importantă | `worker_handler.py` | Workerul reapelează `ingest()` cu parametri privați (`_existing_import_id`, `_existing_job_id`, `_existing_file_names`) și recalculează hash-ul fișierelor deja stocate (citește încă o dată 65 MB) | `process_import(import_id)` care citește fișierele înregistrate |
| 6 | Importantă | `module.py`, `architecture.txt` | `EbaIngestModule` are metode goale; nu există container, `app/api/router.py` sau `app/main.py`; fiecare modul își face propriul `FastAPI` cu propriile handlere de erori și montare statică, deci un al doilea modul nu poate partaja aplicația | `ModuleSpec` + registru de module + o aplicație centrală; fiecare modul păstrează un `create_app` propriu |
| 7 | Importantă | `schema.sql`, `init_db` | `job.kind` are `CHECK ('validate','load')`, deci un modul nou nu își poate crea joburi; migrările sunt `ALTER TABLE` inline în `init_db` | Migrări SQL numerotate, cu tabel de evidență |
| 8 | Importantă | `core/worker/worker.py`, `app/worker.py` | Un job `processing` mai vechi de 900 s (de la `started_at`) este repus în coadă chiar dacă încă rulează; recuperarea se face doar la pornire; `app/worker.py` creează `Worker` fără schema din setări, deși handlerele o folosesc | Heartbeat din fir separat, recuperare periodică, schema transmisă handlerelor |
| 9 | Importantă | `ingest_service._period_report` | `period ~ '^[0-9]{6}$' AND substr(period,5,2)::int ...`: `AND` nu garantează ordinea, iar PostgreSQL poate încerca conversia înaintea expresiei regulate și da „invalid input syntax for type integer”. Testul tău trece din întâmplare (planul ales); eroarea apare la un fișier cu perioade ca `2020` sau gol. Codul vine din prima mea versiune, deci greșeala este și a mea | `CASE WHEN <regex> THEN <conversie> END` și un test cu `2020`, `202013`, gol |
| 10 | Mică | `worker_handler` | Progresul raportat este mereu 50 | Etape reale |
| 11 | Mică | `get_import` | Până la inspectare, fișierele apar cu `recognised: false`, ceea ce se citește „nerecunoscut” | `null` până la inspectare |
| 12 | Mică | `infrastructure/stanging` | Greșeală de scriere în numele pachetului | `staging` |
| 13 | Atenție | arhiva trimisă | Conținea `.env` (cu șiruri de conexiune), `.venv` (109 MB) și `storage/` (un fișier de date de 62 MB) | `.gitignore`; dacă în `.env` era o parolă reală, schimb-o, fiindcă arhiva a circulat |

**Consecință pentru interfață:** frontendul scris de mine pentru modulul 1 se aștepta ca `POST /api/imports` să întoarcă raportul complet; acum întoarce un job `pending`. Trebuie actualizat să interogheze `GET /api/imports/{id}` până când `job_status` devine `completed` sau `failed` și să afișeze `progress`.

**O regulă descoperită la refactorizare (a produs un blocaj real):** un handler nu are voie să facă `UPDATE` pe rândul `job` în tranzacția lui și trebuie să raporteze progresul **înainte** de orice instrucțiune care blochează rândul. Raportorul de progres folosește alte conexiuni și ar aștepta lacătul ținut de handler, care la rândul lui așteaptă raportorul. Regula este în prompt.

## Starea muncii mele pe codul tău (nelivrată)
În mediul meu am început refacerea: nucleul (migrări numerotate, erori comune, fabrică de aplicații, registru de module, worker cu heartbeat) și modulul de ingestie pe straturi; testele tale trec toate 25 (una modificată: `recognised` este `null` înainte de inspectare). Am început și modulul nou: partea de analiză (previzualizare, profil, valori nule, histogramă, scatter) are 29 de teste care trec, iar validarea are 4 din 6 teste trecute: unul a prins o greșeală reală (conversia nesigurată de la punctul 9, în regula V06), celălalt avea o așteptare greșită scrisă de mine. Nu am livrat codul: ai cerut promptul. Dacă preferi să primești codul, îl termin și îl livrez ca arhivă.
