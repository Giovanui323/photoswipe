# PhotoSwipe — regole per chi modifica il codice

## Si lavora sempre su `main`

- Tutto il lavoro si fa direttamente sul ramo `main`: niente rami paralleli (`migliorie` o simili).
- Prima di cominciare controlla di essere su `main` (`git branch --show-current`) e allineato a
  `origin/main`.

## app.py deve solo diminuire, con obiettivo 2.000 righe

L'obiettivo è che `app.py` arrivi a **2.000 righe** e non superi mai più quel numero: ogni
passo deve avvicinarlo a 2.000, mai allontanarlo.

`app.py` è troppo grande (5.777 righe al 20/10/2026, una sola `MainWindow` con ~360 attributi
e 8 pool di thread). È il punto più fragile dell'app.

- **Ogni modifica che tocca `app.py` deve lasciarlo più corto di prima**, o almeno non più lungo.
  Il codice nuovo va in un modulo a parte, non in `app.py`.
- **A ogni occasione porta fuori qualcosa**: quando lavori vicino a una parte che si può
  separare, spostala in un modulo dedicato (anche se il compito non lo chiedeva), purché sia
  uno spostamento sicuro e coperto dai test.
- Candidati da portare fuori, dal più facile:
  - widget autonomi (`ImageView`, `FilmStrip`, `SnapGallery`, `ThumbStrip`, `ElidedLabel`,
    `TrashButton`, `OverlayLabel`, `TipStyle`) → per esempio `widgets/`
  - funzioni di conversione e utilità (`qimage_to_pil`, `pil_to_qimage`, `fmt_datetime`,
    `render_edit_job`, `uncropped_tone_edit`, `help_html`, `LruCache`, `wait_downloads`)
  - la gestione dei thread (i pool `bg`, `dl`, `pre`, `waiters`, `export_q`, `frames_q`,
    `print_q`, `edit_pool`) in un solo modulo con un'interfaccia chiara
  - la logica che non è interfaccia (sessione, export, navigazione) fuori da `MainWindow`
- Quando sposti codice: lo spostamento va da solo, senza cambiare il comportamento nello
  stesso passo, e i test (`.venv/bin/python -m pytest -q tests`) devono passare prima e dopo.
- Alla fine di ogni lavoro, scrivi quante righe ha `app.py` prima e dopo.
- `tests/test_app_size.py` lo controlla: fallisce se `app.py` supera `APP_PY_MAX_LINES`, e
  fallisce anche quando scende sotto, finché non abbassi il limite al nuovo numero di righe.
  Il limite si abbassa e basta: non alzarlo mai per far passare un test.
