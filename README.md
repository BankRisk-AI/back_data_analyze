# eba_ingest: modulul 1 (încărcarea)

Ia fișierele EBA **originale** (`.csv` sau `.xlsx`, exact cum se descarcă), le păstrează neschimbate, le înregistrează în baza de date și încarcă fiecare fișier de date într-o **tabelă de pregătire** (staging) din PostgreSQL, gata pentru modulul 2 (prelucrarea). Se folosește din linia de comandă, ca bibliotecă Python sau, prin adaptorul HTTP din versiunea 0.2, din interfața React `eba-ingest-ui`.

## Ce face, pas cu pas
1. **Stochează originalul** o singură dată, adresat după conținut (`storage/ab/<sha256>.csv`), în citire-doar. Hash-ul și codificarea (UTF-8 sau cp1252) se calculează într-o singură trecere, în bucăți de 1 MB, deci un fișier de 65 MB nu se citește întreg în memorie.
2. **Refuză** fișierul prea mare (implicit peste 100 MB), același fișier ales de două ori și un fișier cu același sha256 ca unul deja încărcat (`loaded`).
3. **Recunoaște tipul** din nume (`tr_oth`, `tr_cre`, `tr_mrk`, `tr_sov`, `SDD`, `TR_Metadata`; numele pot avea sufixe) și îl verifică din conținut: fișierele de date trebuie să aibă coloanele `LEI_Code, NSA, Period, Item, Label, Amount`; `TR_Metadata` trebuie să aibă foaia „Bank list”; `SDD` trebuie să aibă coloanele `Item` și `Dataset`.
4. **Încarcă fișierele de date** în `staging.f<file_id>` (tabelă UNLOGGED, toate coloanele text, nume normalizate: litere mici, `_` în loc de spațiu), prin `COPY` în flux. Fișierele `.xlsx` se citesc doar pentru valori (fără formule); numerele întregi stocate ca `202003.0` devin `202003`.
5. **Raportează** pentru fiecare fișier: rânduri, rânduri agregate (LEI din litere X sau țara OT), perechile (an, trimestru) cu numărul de bănci și de rânduri, avertismente (perioade care nu sunt sfârșit de trimestru, perioade care nu sunt AAAALL).
6. **Scrie urma în baza de date** (schema cu 13 tabele): `import_batch`, `source_file`, `job` (validate), `decision_log` (pasul `ingest_report`, cu raportul întreg în JSON) și `audit_log`.
7. **Totul este atomic**: orice eroare (fișier corupt, rând cu mai multe valori decât antetul, utilizator inexistent) anulează tranzacția, nu lasă tabele de pregătire orfane și șterge copiile stocate de apelul respectiv.

## Instalare
Python 3.11+, PostgreSQL 13+ (testat pe 16.15), o bază de date goală și un utilizator cu drept de creare de scheme.
```
pip install -r requirements.txt
export EBA_DSN="postgresql://utilizator:parola@localhost/numebaza"
python -m eba_ingest init-db          # creează cele 13 tabele și schema staging
```

## Folosire
```
python -m eba_ingest load tr_oth_2.csv tr_cre_2.csv tr_mrk_2.csv SDD_2.xlsx TR_Metadata_2.xlsx --storage ./storage --user 1 --edition 2020
python -m eba_ingest show 1            # raportul unui import (JSON)
python -m eba_ingest drop-staging 1    # șterge tabelele de pregătire ale importului
```
`--user` este id-ul din `app_user` (creează un utilizator înainte). Codul de ieșire este 0 la succes, 2 dacă fișierele sunt refuzate (duplicat, prea mare, ilizibil), 3 dacă importul este respins. Din Python:
```python
from eba_ingest import ingest
rep = ingest(["tr_cre_2.csv"], dsn, "./storage", user_id=1)
print(rep.status, [(p.year, p.quarter, p.banks, p.rows) for p in rep.files[0].pairs])
```

## Adaptor HTTP pentru interfață (versiunea 0.2)
```
python -m eba_ingest serve --storage ./storage --port 8000              # doar API-ul, pentru `npm run dev` din eba-ingest-ui
python -m eba_ingest serve --storage ./storage --ui-dir ../eba-ingest-ui/dist   # un singur proces: API + interfața construită, la http://localhost:8000
```
Nu adaugă logică nouă: fiecare punct de acces apelează o funcție a modulului. Erorile sunt `application/problem+json` (RFC 9457).

| Punct de acces | Funcția modulului | Răspuns |
|---|---|---|
| `GET /api/config` | – | limita de încărcare, extensii acceptate, `authentication: false` |
| `POST /api/imports` (multipart: `files`, `edition`) | `enqueue_import` | 201 cu job `pending`; 409 `duplicate-file`, 413 `file-too-large`, 422 `unreadable-file` |
| `GET /api/imports` | `list_imports` | lista importurilor, cele mai noi primele |
| `GET /api/imports/{id}` | `get_import` | raportul și starea; 404 dacă nu există |
| `DELETE /api/imports/{id}/staging` | `drop_staging` | `{"dropped": n}` |

Nu are autentificare: folosește-l doar pe un calculator de dezvoltare, de încredere. Fișierele încărcate se copiază întâi într-un folder temporar, apoi se stochează, deci un fișier de 65 MB ocupă pe disc, pentru scurt timp, de două ori.

## Worker și dezvoltare

API-ul doar stochează fișierele și creează un job `pending`; workerul independent procesează joburile cu PostgreSQL `FOR UPDATE SKIP LOCKED`. Statusurile jobului sunt `pending`, `processing`, `completed` și `failed`, iar răspunsul importului include `job_status`, `progress` și `progress_message`. Joburile `processing` rămase blocate sunt reintroduse automat în coadă după perioada configurată.

```bash
make dev       # API
make worker    # proces separat pentru importuri
make test      # testele PostgreSQL
```

## Teste
`python -m pytest -q tests` (23 de teste; necesită `EBA_TEST_DSN`, implicit `postgresql://bench:bench@localhost/ing`). `tests/test_real_files.py` rulează pe fișierele originale din 2020 dacă folderul din `EBA_REAL_DIR` le conține (altfel este sărit).

## Contractul cu modulul 2
- Tabelele de pregătire: `staging.f<file_id>`, cu `file_id` din `source_file`; coloanele sunt cele ale fișierului, normalizate, toate `text`; celulele goale sunt `NULL`.
- Starea importului după încărcare: `uploaded`. Trecerea la `validated` o face modulul 2, după validare.
- Raportul încărcării: `decision_log` (`step = 'ingest_report'`).
- Rândul agregat nu este șters în această etapă: este doar numărat (decizia este a modulului 2).

## Limite cunoscute
- Fișierele `.xlsx` de date au fost testate doar pe date sintetice mici; un `tr_cre` în format Excel (circa 400.000 de rânduri) se citește mult mai lent decât CSV și nu a fost măsurat.
- Verificarea fișierelor SDD și TR_Metadata este ușoară (foi și coloane-cheie); conținutul lor se analizează în modulul 2.
- Tabelele de pregătire au toate coloanele text, deci ocupă de circa două ori mai mult decât originalul (133 MB față de 65 MB pentru tr_cre); sunt UNLOGGED, deci se pierd la o cădere a serverului, ceea ce este acceptabil, fiindcă se pot reface din original.
- Nu se ocupă de încărcări simultane ale aceluiași fișier de către utilizatori diferiți mai departe de verificarea hash-ului.
