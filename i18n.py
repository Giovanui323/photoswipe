"""Lingua dell'interfaccia: italiano se il sistema è in italiano, altrimenti inglese.

Il testo sorgente è sempre l'italiano: `tr("Testo")` lo restituisce com'è in italiano e lo traduce
in inglese cercandolo in EN. Testi con segnaposto: `tr("Foto {n}", n=3)`, come str.format.
Per forzare una lingua (es. test): variabile d'ambiente PHOTOSWIPE_LANG=it oppure =en."""
import os

from PySide6.QtCore import QLocale


def _detect() -> str:
    forced = os.environ.get("PHOTOSWIPE_LANG", "").strip().lower()
    if forced in ("it", "en"):
        return forced
    return "it" if QLocale().language() == QLocale.Language.Italian else "en"


LANG = _detect()


def tr(text: str, **kw) -> str:
    if LANG == "en":
        text = EN.get(text, text)
    return text.format(**kw) if kw else text


EN = {
    "Foto precedente": "Previous photo",
    "Foto successiva": "Next photo",
    "Confronta con la copia per la stampa": "Compare with the print copy",
    "Creo la copia per la stampa in export/Stampa. L'originale non si tocca.": "I'll create the print copy in export/Stampa. The original is not touched.",
    "Premuto: mostra la copia per la stampa. Di nuovo: torna alla foto.": "Pressed: shows the print copy. Press again: back to the photo.",
    "Copia per la stampa": "Print copy",
    "Preparo la copia per la stampa… {v0}%": "Preparing the print copy… {v0}%",
    "\n\nIniziato il {v0}\nUltima modifica il {v1}\nExport: {v2}": "\n\nStarted on {v0}\nLast change on {v1}\nExport: {v2}",
    "\n\n← = torna indietro a rivedere": "\n\n← = go back to review",
    "\n\n🎬 {hidden} nascosti dal filtro attivo": "\n\n🎬 {hidden} hidden by the active filter",
    "\n📷 {v0} foto prese dai video": "\n📷 {v0} photos taken from videos",
    "   ({hidden} nascosti dal filtro)": "   ({hidden} hidden by the filter)",
    "   ⏳ export {busy}": "   ⏳ exporting {busy}",
    "   📷 {v0} foto da video": "   📷 {v0} photos from video",
    "<b>In questa cartella c'è un lavoro a metà</b> (interrotto il {when}).<br>Vuoi riprendere da dove eri?":
        "<b>This folder has unfinished work</b> (interrupted on {when}).<br>Do you want to resume where you left off?",
    "<b>Questa cartella è già stata completata</b> (chiuso il {v0}).<br>Vuoi riaprirla?":
        "<b>This folder has already been completed</b> (closed on {v0}).<br>Do you want to reopen it?",
    "<br><a style='color:#0a84ff' href='{url}'>Apri nella mappa</a>":
        "<br><a style='color:#0a84ff' href='{url}'>Open in Maps</a>",
    "<span style='color:#8e8e93'>nessuna posizione nel file</span>":
        "<span style='color:#8e8e93'>no location in the file</span>",
    "<span style='font-size:13px; font-weight:700; color:#ffd60a;'>{done} / {v1} già fatte</span>":
        "<span style='font-size:13px; font-weight:700; color:#ffd60a;'>{done} / {v1} done</span>",
    "Accendi / spegni questa regolazione (per confrontare)": "Turn this adjustment on / off (to compare)",
    "Analisi video non riuscita: {res}": "Video analysis failed: {res}",
    "Annulla": "Cancel",
    "Annulla le modifiche": "Discard edits",
    "Conferma le modifiche": "Confirm edits",
    "Home: torna alla scelta della cartella (la sessione resta salvata).": "Home: back to choosing the folder (the session is kept).",
    "Prima conferma o annulla le modifiche": "First confirm or discard the edits",
    "Annulla questa regolazione": "Reset this adjustment",
    "Anteprima dell'elemento che arriva dopo questa scelta.": "Preview of the item that comes after this decision.",
    "Anteprima non disponibile per {v0}\nSÌ copia comunque il DNG originale in export.":
        "Preview not available for {v0}\nYES will still copy the original DNG to export.",
    "Apre in {FILE_MANAGER} la cartella con le foto approvate.": "Opens the folder with the approved photos in {FILE_MANAGER}.",
    "Apri foto": "Open photo",
    "Apri video": "Open video",
    "Aspetta che la foto sia caricata": "Wait for the photo to load",
    "Attendi: sto analizzando il video…": "Please wait: analyzing the video…",
    "Automatico: è già dritta": "Automatic: already straight",
    "Bianco e nero": "Black & White",
    "Carico la foto in 4K…": "Loading the photo in 4K…",
    "Cartella da guardare": "Folder to browse",
    "Cartella dove copiare le scelte": "Folder to copy the choices to",
    "Cartella dove vengono COPIATE le foto approvate. Gli originali non si toccano.":
        "Folder where the approved photos are COPIED. The originals are not touched.",
    "Clic sulla striscia per fermarti su un fotogramma  ·  SÌ = copia il video in export/Video":
        "Click the strip to stop on a frame  ·  YES = copy the video to export/Video",
    "Completo gli export in corso… ({left})\n\nLe copie non finite verranno rifatte alla prossima apertura.":
        "Finishing the exports in progress… ({left})\n\nUnfinished copies will be redone the next time you open the folder.",
    "Conferma il ritaglio (Invio). Poi con ✓ Sì si esporta la foto ritagliata.":
        "Confirm the crop (Enter). Then ✓ Yes exports the cropped photo.",
    "Conferma le modifiche (Invio). Poi ✓ Sì esporta la foto modificata.":
        "Confirm the edits (Enter). Then ✓ Yes exports the edited photo.",
    "Confronta: mostra la foto originale (di nuovo = torna alla modificata).":
        "Compare: shows the original photo (press again to go back to the edited one).",
    "Corregge la prospettiva da sinistra a destra.": "Corrects the perspective from left to right.",
    "Da: {last}\nExport: {last_exp}": "From: {last}\nExport: {last_exp}",
    "Download da iCloud non riuscito:\n{res}": "iCloud download failed:\n{res}",
    "ERRORE qualità": "QUALITY ERROR",
    "Elemento {pos} di {v1}\n✓ {v2} approvate\n✗ {v3} scartate\n↪ {v4} saltate":
        "Item {pos} of {v1}\n✓ {v2} approved\n✗ {v3} discarded\n↪ {v4} skipped",
    "Errore nella lettura della cartella: {res}": "Error reading the folder: {res}",
    "Esplora file": "File Explorer",
    "Export non riuscito per {v0}: {res} (la scelta resta: si riprova alla prossima apertura)":
        "Export failed for {v0}: {res} (the choice stays: it will be retried the next time you open the folder)",
    "Export: {v0}": "Export: {v0}",
    "Fai clic su ogni occhio rosso nella foto.\nIl cursore regola la misura del cerchio.":
        "Click each red eye in the photo.\nThe slider adjusts the size of the circle.",
    "Foto + video (⇧Y)": "Photo + video (⇧Y)",
    "Foto tolta: fotogramma {v0} (F per riprenderla)": "Photo removed: frame {v0} (F to take it again)",
    "Fotogramma {v0} / {v1}  ·  ": "Frame {v0} / {v1}  ·  ",
    "GIÀ SCELTO  {v0}": "ALREADY DECIDED  {v0}",
    "Impossibile aprire {v0}": "Cannot open {v0}",
    "Impossibile leggere il lavoro salvato in questa cartella: {e}": "Cannot read the saved work in this folder: {e}",
    "Impossibile modificare {v0}: anteprima non disponibile": "Cannot edit {v0}: preview not available",
    "Impostazioni: cartella, export, filtro, formato e ora.": "Settings: folder, export, filter, format and time.",
    "Informazioni sulla foto e sulla selezione.": "Information about the photo and the selection.",
    "Intensità": "Strength",
    "JPEG qualità massima": "JPEG maximum quality",
    "La bacchetta magica funziona su foto, panorami, Live e fotogrammi fermi dei video":
        "The magic wand works on photos, panoramas, Lives and the still frames of videos",
    "La cartella export non può essere la stessa da guardare: scegline o creane un'altra.":
        "The export folder can't be the same as the folder to browse: choose or create another one.",
    "La cartella export non può stare dentro “{TRASH_DIR}”: lì vanno solo gli originali messi da parte.":
        "The export folder can't be inside “{TRASH_DIR}”: only the set-aside originals go there.",
    "Lascia la foto com'era prima di aprire Ritaglia (Esc).": "Leave the photo as it was before opening Crop (Esc).",
    "Lascia la foto com'era prima di queste modifiche (Esc).": "Leave the photo as it was before these edits (Esc).",
    "Lavoro non completato": "Unfinished work",
    "Le foto approvate vengono copiate in:\n{v0}": "Approved photos are copied to:\n{v0}",
    "Le scelte salvate verranno riprese. La cartella export di allora ({v0}) non c'è su questo computer: scegli dove copiare le prossime con ②, poi Inizia.":
        "The saved choices will be resumed. The export folder from before ({v0}) isn't on this computer: choose where to copy the next ones with ②, then Start.",
    "Lettura della cartella…": "Reading the folder…",
    "Luminosità": "Brightness",
    "Miglioramento automatico tolto: Conferma le modifiche": "Auto enhancement removed: Confirm edits",
    "Modifiche annullate: si vede (ed esporta) l'originale": "Edits discarded: the original is shown (and exported)",
    "Modifiche confermate: ✓ Sì esporta la foto modificata": "Edits confirmed: ✓ Yes exports the edited photo",
    "Modifiche pronte: 📷 Prendi foto (F) salva questo fotogramma modificato":
        "Edits ready: 📷 Take photo (F) saves this edited frame",
    "Mostra": "Show",
    "Mostra / nascondi il pannello delle informazioni (I).": "Show / hide the info panel (I).",
    "Mostra export in {FILE_MANAGER}": "Show export in {FILE_MANAGER}",
    "Mostra il file di log": "Show log file",
    "Mostra in {FILE_MANAGER} il file con i progressi.": "Show the progress file in {FILE_MANAGER}.",
    "Mostra la cartella export": "Show export folder",
    "Mostra: da decidere": "Show: undecided",
    "Mostra: già decise": "Show: decided",
    "Mostra: solo foto (anche Live e panorami)": "Show: photos only (also Lives and panoramas)",
    "Mostra: solo video (Live escluse)": "Show: videos only (Lives excluded)",
    "Mostra: tutte": "Show: all",
    "Mostra: tutto": "Show: everything",
    "Mostra: ↪ saltate": "Show: ↪ skipped",
    "Mostra: ✓ Sì": "Show: ✓ Yes",
    "Mostra: ✗ No": "Show: ✗ No",
    "Mostra: 🗑 “cancellare”": "Show: 🗑 “cancellare”",
    "Nessun video in {v0}": "No video in {v0}",
    "Nessuna foto o video trovati in questa cartella.": "No photos or videos found in this folder.",
    "No e cancella (X)": "No and trash (X)",
    "Non riesco a cercare il fotogramma più nitido": "I can't look for the sharpest frame",
    "Ora: della fotocamera": "Time: from the camera",
    "Originale (premi di nuovo □|□ per la versione modificata)": "Original (press again □|□ for the edited version)",
    "Prima conferma il ritaglio con OK oppure Annulla": "First confirm the crop with OK or Cancel",
    "Prima conferma le modifiche con OK oppure Annulla": "First confirm the edits with OK or Cancel",
    "Punto di nero": "Black point",
    "Questo è già il fotogramma più nitido qui vicino": "This is already the sharpest frame nearby",
    "Raddrizza l'orizzonte da solo.": "Levels the horizon automatically.",
    "Raddrizza le linee verticali che convergono (palazzi).": "Straightens the converging vertical lines (buildings).",
    "Regola e Ritaglia: per foto, panorami, Live e il fotogramma fermo dei video":
        "Adjust and Crop: for photos, panoramas, Lives and the still frame of videos",
    "Ricomincia da capo": "Start over",
    "Riprendi da dove eri": "Resume where you left off",
    "Ripreso da dove eri: {done} già decise": "Resumed where you left off: {done} already decided",
    "Ripristino da “cancellare” non riuscito: {e} (riprova)": "Restoring from “cancellare” failed: {e} (try again)",
    "Ritaglio confermato: ✓ Sì esporta la foto ritagliata": "Crop confirmed: ✓ Yes exports the cropped photo",
    "Ruota la foto (doppio clic = 0°). ⌥ mentre trascini = più preciso.":
        "Rotates the photo (double-click = 0°). Hold ⌥ while dragging for more precision.",
    "Salva ora": "Save now",
    "Salva video (Y)": "Save video (Y)",
    "Salvataggio non riuscito: {e}": "Saving failed: {e}",
    "Salvataggio non scaricabile da iCloud: {path}": "The save can't be downloaded from iCloud: {path}",
    "Scegli cartella…": "Choose folder…",
    "Scegli la cartella con foto e video (vengono lette anche le sottocartelle).":
        "Choose the folder with photos and videos (subfolders are read too).",
    "Scorri le miniature avanti": "Scroll thumbnails forward",
    "Scorri le miniature indietro": "Scroll thumbnails back",
    "Sei in fondo, ma {rest} da decidere più indietro.": "You're at the end, but {rest} undecided further back.",
    "manca 1 elemento": "1 item is still",
    "mancano {n} elementi": "{n} items are still",
    "Sei al primo elemento": "You're at the first item",
    "Sfocatura: la foto è già nitida": "Blur: the photo is already sharp",
    "Specchia la foto da sinistra a destra.": "Mirrors the photo from left to right.",
    "Spostamento non riuscito: {e}": "Move failed: {e}",
    "Successivo (→): vai all'elemento dopo senza decidere.": "Next (→): go to the next item without deciding.",
    "Sì (Y)": "Yes (Y)",
    "Sì + video (⇧Y)": "Yes + video (⇧Y)",
    "Tieni le foto (Y)": "Keep the photos (Y)",
    "Toglie ritaglio, rotazione e prospettiva.": "Removes crop, rotation and perspective.",
    "Toglie tutte le modifiche (Regola e Ritaglia): torna la foto originale.":
        "Removes all edits (Adjust and Crop): back to the original photo.",
    "Toglie tutte le regolazioni di questa foto (il ritaglio resta).": "Removes all adjustments for this photo (the crop stays).",
    "Tonalità": "Hue",
    "Torna alla foto da cui sei tornato indietro (con ← o B).": "Back to the photo you came back from (with ← or B).",
    "analisi del video…": "analyzing the video…",
    "anteprima 720p · originale scaricato al SÌ": "720p preview · original downloaded on YES",
    "anteprima non letta": "preview not read",
    "cerco il fotogramma più nitido…": "looking for the sharpest frame…",
    "da decidere · niente copiato né spostato": "undecided · nothing copied or moved",
    "della fotocamera": "from the camera",
    "ffmpeg non trovato": "ffmpeg not found",
    "fotogramma non letto": "frame not read",
    "fotogramma {v0}": "frame {v0}",
    "lunedì": "Monday", "martedì": "Tuesday", "mercoledì": "Wednesday", "giovedì": "Thursday",
    "venerdì": "Friday", "sabato": "Saturday", "domenica": "Sunday",
    "gennaio": "January", "febbraio": "February", "marzo": "March", "aprile": "April", "maggio": "May",
    "giugno": "June", "luglio": "July", "agosto": "August", "settembre": "September", "ottobre": "October",
    "novembre": "November", "dicembre": "December",
    "meno di 10×15": "smaller than 10×15",
    "raddrizzata di {a:+.1f}°": "straightened by {a:+.1f}°",
    "scelta da te": "your choice",
    "trascina sulla striscia o usa ↑ ↓ per cambiarla  ·  SÌ salva questa":
        "drag on the strip or use ↑ ↓ to change it  ·  YES saves this one",
    "trascina sulla striscia per sceglierne un'altra": "drag on the strip to choose another one",
    "{state}<br><span style='color:#98989f'>Si salvano da soli a ogni scelta: puoi chiudere quando vuoi e riprendere da qui.</span><table cellspacing='0' style='margin-top:6px'><tr><td style='color:#98989f; padding:2px 10px 2px 0'>Progressi</td><td>{v1}/{v2}</td></tr><tr><td style='color:#98989f; padding:2px 10px 2px 0'>Foto scelte</td><td>{v3}</td></tr></table>":
        "{state}<br><span style='color:#98989f'>Saved automatically with every choice: you can close at any time and resume from here.</span><table cellspacing='0' style='margin-top:6px'><tr><td style='color:#98989f; padding:2px 10px 2px 0'>Progress</td><td>{v1}/{v2}</td></tr><tr><td style='color:#98989f; padding:2px 10px 2px 0'>Photos chosen</td><td>{v3}</td></tr></table>",
    "{v0}  ·  {pos} di {total}": "{v0}  ·  {pos} of {total}",
    "{v0} non disponibile": "{v0} not available",
    "— nessuna cartella scelta —": "— no folder chosen —",
    "— prima scegli la cartella da guardare —": "— first choose the folder to browse —",
    "→  Vai al primo da decidere": "→  Go to the first undecided",
    "↪  Rivedi le saltate": "↪  Review skipped",
    "↪ saltata · niente copiato né spostato": "↪ skipped · nothing copied or moved",
    "①  Scegli la cartella con foto e video da guardare": "①  Choose the folder with photos and videos to browse",
    "②  Scegli (o crea con “Nuova cartella”) dove copiare le approvate":
        "②  Choose (or create with “New folder”) where to copy the approved ones",
    "☁️  Scarico da iCloud{dots}\n\n{names}\n\n{bar}  ≈ {pct}%\n⏱  {secs} s  ·  {eta}   (stima su {speed:.1f} MB/s)\nmacOS non dice la percentuale vera: la stima usa la velocità dei download già fatti.\nI prossimi {PREFETCH} elementi si stanno già scaricando in automatico.\n\nIntanto puoi premere  S = salta,  N = no,  X = sposta in “cancellare”.":
        "☁️  Downloading from iCloud{dots}\n\n{names}\n\n{bar}  ≈ {pct}%\n⏱  {secs} s  ·  {eta}   (estimate at {speed:.1f} MB/s)\nmacOS doesn't report the real percentage: the estimate uses the speed of the downloads so far.\nThe next {PREFETCH} items are already downloading automatically.\n\nMeanwhile you can press  S = skip,  N = no,  X = move to “cancellare”.",
    "☁️ Scarico in anticipo {v0} file ({mb:.0f} MB)": "☁️ Downloading ahead: {v0} files ({mb:.0f} MB)",
    "♥ Preferita: le copie vanno in export/Preferite": "♥ Favorite: copies go to export/Preferite",
    "♥ sì": "♥ yes",
    "⚠ Cartella export non raggiungibile ({v0}): {v1} copie in sospeso verranno rifatte alla prossima apertura":
        "⚠ Export folder not reachable ({v0}): {v1} pending copies will be redone the next time you open the folder",
    "⚠ copia non riuscita: {v0}\n(si riprova alla prossima apertura)":
        "⚠ copy failed: {v0}\n(will be retried the next time you open the folder)",
    "✂︎ Ritaglio aperto: Conferma per confermare, Annulla per lasciarla com'era":
        "✂︎ Crop open: Confirm to confirm, Cancel to leave it as it was",
    "✎ Foto {v0} dopo il Sì: premi di nuovo ✓ Sì per esportare questa versione":
        "✎ Photo {v0} after Yes: press ✓ Yes again to export this version",
    "✎ Foto {v0}: ✓ Sì esporta questa versione": "✎ Photo {v0}: ✓ Yes exports this version",
    "✎ Modifiche da confermare: Conferma per tenerle, Annulla per lasciarla com'era":
        "✎ Edits to confirm: Confirm to keep them, Cancel to leave it as it was",
    "✓ SÌ": "✓ YES",
    "✓ approvata · video non copiato (tenute solo le foto prese)": "✓ approved · video not copied (only the photos taken are kept)",
    "✓ già salvato come foto": "✓ already saved as a photo",
    "✨  Più nitida (P)": "✨  Sharper (P)",
    "✨ Migliorata automaticamente: Conferma per tenerla, Annulla per lasciarla com'era":
        "✨ Auto-enhanced: Confirm to keep it, Cancel to leave it as it was",
    "💽 Cartella su disco (non su iCloud): nessun download, si parte subito.":
        "💽 Folder on disk (not iCloud): no download, starts right away.",
    "📂  Apri cartella…": "📂  Open folder…",
    "📷  Prendi foto (F)": "📷  Take photo (F)",
    "📷  1 foto salvata da questo video": "📷  1 photo saved from this video",
    "📷  {k} foto salvate da questo video": "📷  {k} photos saved from this video",
    "📷 F = salva questo fotogramma come foto": "📷 F = save this frame as a photo",
    "📷 Foto del fotogramma {v0} rifatta con le modifiche": "📷 Photo of frame {v0} redone with the edits",
    "📷 Foto salvata: fotogramma {v0}  (Z per annullare)": "📷 Photo saved: frame {v0}  (Z to undo)",
    "📷 Fotogramma {v0} già salvato": "📷 Frame {v0} already saved",
    "📷 {k} foto prese (segni verdi)  ·  SÌ = tieni solo le foto  ·  ＋ SÌ e video = anche il video":
        "📷 {k} photos taken (green marks)  ·  YES = keep only the photos  ·  ＋ YES and video = the video too",
    "📸 Foto della Live: fotogramma {v0}  (SÌ per salvarla)": "📸 Live photo: frame {v0}  (YES to save it)",
    "📸 Foto: fotogramma {v0} / {v1} ({who})  ·  ": "📸 Photo: frame {v0} / {v1} ({who})  ·  ",
    "🖼  Torna alla foto (L)": "🖼  Back to the photo (L)",
    "🗑 originale SPOSTATO in “cancellare” (Z lo rimette a posto)": "🗑 original MOVED to “cancellare” (Z puts it back)",
    "  Opzioni": "  Options",
    "›  Opzioni": "›  Options",
    "Audio: ": "Audio: ",
    "Automatico: ": "Automatic: ",
    "Bianco (ingresso)": "White (input)",
    "Bianco (uscita)": "White (output)",
    "Nero (ingresso)": "Black (input)",
    "Nero (uscita)": "Black (output)",
    "Bilanc. del bianco": "White balance",
    "Cartella export: dove copiare quelle approvate": "Export folder: where to copy the approved ones",
    "Colore selettivo": "Selective color",
    "Dopo:  fine 🎉": "Next:  done 🎉",
    "ERRORE NON GESTITO": "UNHANDLED ERROR",
    "ERRORE copia": "COPY ERROR",
    "Export: —": "Export: —",
    "FOTOGRAMMI ESPORTATI": "EXPORTED FRAMES",
    "Finito!": "Done!",
    "Forma libera": "Free form",
    "Foto annullata": "Photo discarded",
    "Fotogramma precedente (↑, Maiusc+↑ = 10 indietro)": "Previous frame (↑, Shift+↑ = 10 back)",
    "Fotogramma successivo (↓, Maiusc+↓ = 10 avanti)": "Next frame (↓, Shift+↓ = 10 forward)",
    "Fuso orario": "Time zone",
    "Lavoro completato": "Work completed",
    "Modifiche annullate": "Edits discarded",
    "Nuova selezione…": "New selection…",
    "Occhi rossi": "Red-eye",
    "PNG 16-bit (senza perdita)": "PNG 16-bit (lossless)",
    "Pausa (barra spaziatrice)": "Pause (space bar)",
    "Play (barra spaziatrice)": "Play (space bar)",
    "Play / Pausa (barra spaziatrice)": "Play / Pause (space bar)",
    "Preferita tolta": "Favorite removed",
    "Regolazione automatica": "Auto adjustment",
    "Reimposta regolazioni": "Reset adjustments",
    "Riduz. disturbo": "Noise reduction",
    "Ripristina originale": "Restore original",
    "Ritaglio annullato": "Crop discarded",
    "Se vuoi esserne sicuro, questo salva subito.": "If you want to be sure, this saves right away.",
    "Togli l'ultimo": "Remove the last one",
    "Toni neutri": "Neutral tones",
    "Z annulla l'ultima presa.": "Z undoes the last one taken.",
    "quasi finito…": "almost done…",
    "salvo…": "saving…",
    "⏳ copia in export in corso…": "⏳ copying to export…",
    "↪  Salta questo  (S)": "↪  Skip this  (S)",
    "↪ Salta": "↪ Skip",
    "↺  Originale (R)": "↺  Original (R)",
    "⇋   Capovolgi": "⇋   Flip",
    "▦   Proporzioni": "▦   Aspect ratio",
    "▶  Vedi Live (L)": "▶  Show Live (L)",
    "☁️ in download": "☁️ downloading",
    "⚠ profilo colore piatto (D-Log/HLG)": "⚠ flat color profile (D-Log/HLG)",
    "✓ approvata · COPIATA in export (l'originale resta al suo posto)":
        "✓ approved · COPIED to export (the original stays where it is)",
    "✗ scartata · niente copiato, l'originale resta al suo posto":
        "✗ discarded · nothing copied, the original stays where it is",
    "⟲  Rivedi (V)": "⟲  Replay (V)",
    "⤳  Torna all'analisi": "⤳  Back to the analysis",
    "⤳ Torna all'ultima": "⤳ Back to the last one",
    "💾 Progressi salvati": "💾 Progress saved",
    "🗑 In “cancellare”": "🗑 In “cancellare”",
    "(si riprova alla prossima apertura)": "(will be retried the next time you open the folder)",
    "(disco scollegato?).": "(disconnected drive?).",
    "?  Come funziona": "?  How it works",
    "AIUTO": "HELP", "CARTELLE": "FOLDERS", "Cartella": "Folder", "Chiudi": "Close", "Dettagli": "Details",
    "ERRORE": "ERROR", "Export": "Export", "FOTO": "PHOTO", "INFO": "INFO", "Info": "Info", "LIVE": "LIVE",
    "Luogo": "Location", "Nota": "Note", "Preferita": "Favorite", "Regola": "Adjust", "Riapri": "Reopen",
    "Ritaglia": "Crop", "SALVATAGGIO": "SAVING", "SELEZIONE": "SELECTION", "Stato": "Status", "Tipo": "Type",
    "VIDEO": "VIDEO", "VISUALIZZA": "VIEW", "Stampa": "Print", "Salva ora": "Save now",
    "AUTO": "AUTO", "Attenuazione": "Attenuation", "Automatico": "Automatic", "Cognome": "Whites",
    "Bianco e nero": "Black & White", "Bordi": "Edges", "Brillantezza": "Brilliance", "Colore": "Color",
    "Contrasto": "Contrast", "Curve": "Curves", "Definizione": "Definition", "Dimensione": "Size",
    "Dominante": "Cast", "Esposizione": "Exposure", "Grana": "Grain", "Livelli": "Levels", "Luce": "Light",
    "Luci": "Highlights", "Luminanza": "Luminance", "Mezzitoni": "Midtones", "Morbidezza": "Softness",
    "Neri": "Blacks", "Nitidezza": "Sharpness", "Ombre": "Shadows", "Orizzontale": "Horizontal",
    "REGOLA": "ADJUST", "RITAGLIA": "CROP", "Raddrizza": "Straighten", "Raggio": "Radius",
    "Reimposta": "Reset", "Saturazione": "Saturation", "Sfocatura": "Blur", "Temperatura": "Temperature",
    "Tinta": "Tint", "Tono": "Tone", "Verticale": "Vertical", "Vividezza": "Vibrance", "Vignettatura": "Vignette",
    "Blu": "Blue", "Ciano": "Cyan", "Giallo": "Yellow", "Magenta": "Magenta", "Originale": "Original",
    "Personalizzato": "Custom", "Quadrato": "Square", "Rosso": "Red", "Verde": "Green",
    "Audio": "Audio", "Bitrate": "Bitrate", "Durata": "Duration", "File": "File", "Fotocamera": "Camera",
    "Obiettivo": "Lens", "Scatto": "Shot", "Video": "Video", "Dimensioni": "Size",
    "Stampabilità": "Printability", "{v0} a 300 dpi": "{v0} at 300 dpi", "{v0} a 200 dpi": "{v0} at 200 dpi",
    "troppo piccola per una stampa di qualità": "too small for a good-quality print",
    "ottima": "excellent", "buona": "good", "discreta": "fair", "scarsa": "poor",
    "STAMPA": "PRINT", "Migliora per la stampa": "Improve for print",
    "Copia per la stampa salvata: {v0}  ({v1})": "Print copy saved: {v0}  ({v1})",
    "Non riesco a preparare questa foto per la stampa": "I can't prepare this photo for print",
    "{v0} × {v1} px: {v2}": "{v0} × {v1} px: {v2}",
    "FOTO PRESA · FOTOGRAMMA {v0}": "TAKEN PHOTO · FRAME {v0}",
    "Correggi": "Fix", "Aggiorna foto": "Update photo", "Chiudi ✕": "Close ✕",
    "Modifica il fotogramma, poi premi \"Aggiorna foto\"": "Edit the frame, then press \"Update photo\"",
}

EN.update({
    "\n(questa cartella export non c'è su questo computer: riprendendo ti chiedo dove copiare)":
        "\n(this export folder isn't on this computer: when resuming I'll ask where to copy)",
    "Al posto originale c'era già un file con lo stesso nome: nessuno è stato sovrascritto. Ripristinati come:\n":
        "The original spot already had a file with the same name: nothing was overwritten. Restored as:\n",
    "Annulla l'ultima scelta e torna indietro (Z).\nSe era un Sì, toglie anche i file copiati in export.":
        "Undo the last choice and go back (Z).\nIf it was a Yes, it also removes the files copied to export.",
    "Clic o trascina sulla striscia per scegliere il fotogramma.\nLive: quello scelto diventa la foto (SÌ salva questa).\nLive: il pallino giallo è la foto scelta dalla fotocamera (R per tornarci).\nVideo: si ferma lì, poi 📷 Prendi foto.  ↑ ↓ un fotogramma alla volta.":
        "Click or drag on the strip to choose the frame.\nLive: the one you pick becomes the photo (YES saves it).\nLive: the yellow dot is the photo chosen by the camera (R to go back to it).\nVideo: it stops there, then 📷 Take photo.  ↑ ↓ one frame at a time.",
    "Come funziona (? o H): spiega tutti i pulsanti e i tasti.\nDa qui apri anche il file di log.":
        "How it works (? or H): explains all buttons and keys.\nFrom here you can also open the log file.",
    "Formato dei fotogrammi estratti da Live e video.\nJPEG qualità massima: accettato da tutti i siti di stampa.\nPNG 16-bit: senza perdita, file molto grandi (~40 MB).\nFoto e panorami vengono sempre copiati identici.":
        "Format of the frames extracted from Lives and videos.\nJPEG maximum quality: accepted by all print services.\nPNG 16-bit: lossless, very large files (~40 MB).\nPhotos and panoramas are always copied as they are.",
    "Foto adattata alla finestra; due dita su/giù o pizzico = zoom, doppio clic = adatta.\n\n    Adattata: l'immagine viene ridotta UNA volta, con filtro di alta qualità, ai pixel reali dello\n    schermo (Retina compreso), invece di lasciarla ridurre al volo (più morbido/scalettato).\n    Con lo zoom si passa all'originale a piena risoluzione.":
        "Photo fitted to the window; two fingers up/down or pinch = zoom, double-click = fit.\n\n    Fitted: the image is scaled DOWN once, with a high-quality filter, to the real pixels of the\n    screen (Retina included), instead of being scaled on the fly (softer/jagged).\n    Zooming in goes to the original at full resolution.",
    "Foto prese da questo video con 📷 Prendi foto.\nRestano salvate in export anche se premi NO.\nZ annulla l'ultima presa.":
        "Photos taken from this video with 📷 Take photo.\nThey stay saved in export even if you press NO.\nZ undoes the last one taken.",
    "Foto prese da questo video.\nClic: il video torna su quel fotogramma per rivederlo.\nDoppio clic: apre il file salvato.\n✕: toglie la foto da export (puoi riprenderla con F).":
        "Photos taken from this video.\nClick: the video goes back to that frame to review it.\nDouble-click: opens the saved file.\n✕: removes the photo from export (you can take it again with F).",
    "Fuso orario scritto nella data delle foto esportate.\n'Della fotocamera' usa l'ora registrata in ogni file.":
        "Time zone written into the date of the exported photos.\n'From the camera' uses the time recorded in each file.",
    "Inizia  ▶": "Start  ▶",
    "La cartella copiata dalla scheda SD (per esempio DCIM). Vengono lette anche tutte le sottocartelle.":
        "The folder copied from the SD card (for example DCIM). All subfolders are read too.",
    "La cartella dell'ultima sessione non è raggiungibile (disco scollegato?).":
        "The last session's folder can't be reached (disconnected drive?).",
    "La cartella export non può contenere la cartella da guardare: scegline o creane un'altra.":
        "The export folder can't contain the folder to browse: choose or create another one.",
    "Le foto approvate vengono copiate qui, i video nella sottocartella “Video”. Gli originali non vengono mai spostati né modificati.":
        "Approved photos are copied here, videos into the “Video” subfolder. The originals are never moved or changed.",
    "Le foto prima e dopo questa. Clic per andarci.\nIl pallino colorato è la scelta già fatta.":
        "The photos before and after this one. Click to go there.\nThe colored dot is the choice already made.",
    "Le scelte salvate verranno messe da parte (il file viene rinominato, non cancellato).\nLe foto già copiate in export restano dove sono.\n\nContinuare?":
        "The saved choices will be set aside (the file is renamed, not deleted).\nPhotos already copied to export stay where they are.\n\nContinue?",
    "Luce, colore, bianco e nero, curve, nitidezza…\n✓ Sì esporta la foto modificata (l'originale non si tocca).":
        "Light, color, black & white, curves, sharpness…\n✓ Yes exports the edited photo (the original is not touched).",
    "Migliora automaticamente (bacchetta magica): Luce e Colore automatici.\nDi nuovo = toglie il miglioramento. Poi Conferma le modifiche.":
        "Improves automatically (magic wand): automatic Light and Color.\nPress again to remove the enhancement. Then Confirm edits.",
    "Non serve: si salva da solo a ogni scelta.\nSe vuoi esserne sicuro, questo salva subito.":
        "Not needed: it saves itself with every choice.\nIf you want to be sure, this saves right away.",
    "Precedente (← o B): torna all'elemento prima, anche se già deciso\n(approvato, scartato, in “cancellare”). La nuova scelta sostituisce la vecchia.":
        "Previous (← or B): go back to the previous item, even if already decided\n(approved, discarded, in “cancellare”). A new choice replaces the old one.",
    "Preferita (.): le preferite approvate vengono copiate in\nexport/Foto/Preferite invece che in export/Foto.":
        "Favorite (.): approved favorites are copied to\nexport/Foto/Preferite instead of export/Foto.",
    "Quali miniature mostrare nella striscia in basso.\nQuella che stai guardando resta sempre visibile.":
        "Which thumbnails to show in the strip at the bottom.\nThe one you're looking at always stays visible.",
    "Questo elemento è già stato deciso. Premi un'altra scelta per cambiarla:\nla nuova sostituisce la vecchia e i file tornano a posto (Z annulla).":
        "This item has already been decided. Press another choice to change it:\nthe new one replaces the old and the files are put back in place (Z undoes).",
    "Recupera un po' di nitidezza nelle foto sfocate o leggermente mosse.\nAUTO stima quanto è sfocata; Raggio = quanto era sfocata.":
        "Recovers some sharpness in blurred or slightly shaken photos.\nAUTO estimates how blurred it is; Radius = how blurred it was.",
    "Ritaglia, raddrizza e proporzioni. Conferma con OK,\npoi ✓ Sì esporta la foto ritagliata.":
        "Crop, straighten and aspect ratio. Confirm with OK,\nthen ✓ Yes exports the cropped photo.",
    "Salta (S)": "Skip (S)",
    "Salva SUBITO come foto il fotogramma che stai guardando (F)\ne resta su questo video: puoi prenderne quante vuoi.\nLe foto salvate sono i segni verdi sulla striscia.\nPoi con SÌ / NO decidi se tenere anche il video.":
        "Save the frame you're looking at as a photo RIGHT NOW (F)\nand stay on this video: you can take as many as you like.\nSaved photos are the green marks on the strip.\nThen with YES / NO decide whether to keep the video too.",
    "Solo foto: nasconde i video (restano foto, Live e panorami).\nSolo video: nasconde foto, Live e panorami.\nGli elementi nascosti non vengono toccati: li ritrovi con 'Mostra: tutto'.":
        "Photos only: hides videos (photos, Lives and panoramas stay).\nVideos only: hides photos, Lives and panoramas.\nHidden items are not touched: you'll find them again with 'Show: everything'.",
    "Toglie regolazioni e ritaglio da questa foto: torna l'originale.\n(Se l'avevi già approvata, premi di nuovo ✓ Sì per esportarla com'era.)":
        "Removes adjustments and crop from this photo: back to the original.\n(If you had already approved it, press ✓ Yes again to export it as it was.)",
    "Torna alla prima foto ancora da decidere\n(la prossima da giudicare)":
        "Go back to the first photo still to decide\n(the next one to judge)",
    "Trascina gli angoli o i lati del riquadro sulla foto; trascina dentro per spostarlo.\nPoi Conferma le modifiche (o Annulla).":
        "Drag the corners or sides of the frame on the photo; drag inside to move it.\nThen Confirm edits (or Cancel).",
    "Video: fermati sul fotogramma da salvare (pausa o clic sulla striscia), poi Regola o Ritaglia":
        "Video: stop on the frame to save (pause or click the strip), then Adjust or Crop",
    "Zoom (anche due dita sul trackpad o rotella; doppio clic = foto intera)":
        "Zoom (also two fingers on the trackpad or wheel; double-click = whole photo)",
    "copia identica": "identical copy",
    "sì": "yes",
})


EN.update({
    "PANORAMA": "PANORAMA", "Sì": "Yes", "Selezione": "Selection", "Salvataggio": "Saving",
    "Modificata": "Edited", "Ripeti": "Loop", "Disattiva": "Off", "✗ NO": "✗ NO",
    "Capovolgi": "Flip", "Proporzioni": "Aspect ratio",
    "Raddrizza l'orizzonte e le linee verticali da solo.": "Straightens the horizon and vertical lines by itself.",
    "Clic di nuovo per passare da orizzontale a verticale": "Click again to switch between landscape and portrait",
    "Crea una copia per la stampa in export/Stampa: ingrandisce con Real-ESRGAN (se installato) o Lanczos, e aggiunge nitidezza. L'originale non si tocca.":
        "Creates a print copy in export/Stampa: upscales with Real-ESRGAN (if installed) or Lanczos and adds sharpening. The original is never touched.",
    " (ingrandimento semplice: per la qualità migliore installa il Visual C++ Redistributable gratuito di Microsoft: {url})":
        " (simple upscaling: for the best quality install Microsoft's free Visual C++ Redistributable: {url})",
    "Rinomina per data": "Rename by date",
    "Rinomina le copie approvate in export in ordine di data e ora di scatto. Gli originali non si toccano.":
        "Renames the approved copies in export in order of capture date and time. The originals are never touched.",
    "Rinomino {v0} foto approvate in export in ordine di data e ora.\nGli originali non si toccano.\n\nContinuare?":
        "I'll rename {v0} approved photos in export in order of date and time.\nThe originals are never touched.\n\nContinue?",
    "Copie rinominate: {v0}": "Copies renamed: {v0}",
    "Aspetta che finiscano le copie in corso, poi rinomina": "Wait for the copies in progress to finish, then rename",
    "Cartella export non raggiungibile": "Export folder not reachable",
    "Nessuna copia da rinominare": "No copies to rename",
    "Rinomina non riuscita: {e}": "Rename failed: {e}",
    "Alcune copie non si sono potute rinominare e sono rimaste com'erano:\n":
        "Some copies could not be renamed and were left as they were:\n",
    "Questi file non sono più in “cancellare” e non si possono rimettere a posto:\n":
        "These files are no longer in “cancellare” and can't be put back:\n",
    "Audio acceso / spento (Live e video)": "Sound on / off (Live and videos)",
    "Come si riproduce la Live quando fai clic sulla foto": "How the Live plays when you click the photo",
    "Foto prese da questo video.\nClic: il video torna su quel fotogramma per rivederlo.\nDoppio clic: mostra la foto intera, con stampabilità e correzioni.\n✕: toglie la foto da export (puoi riprenderla con F).":
        "Photos taken from this video.\nClick: the video goes back to that frame to review it.\nDouble-click: shows the whole photo, with print check and fixes.\n✕: removes the photo from export (you can take it again with F).",
    "Preparo la copia per la stampa…": "Preparing the print copy…",
    "Preparo la copia per la stampa… può richiedere qualche minuto": "Preparing the print copy… it may take a few minutes",
    "<span style='color:#7fe3b4'>✓ Salvato alle {when}</span>": "<span style='color:#7fe3b4'>✓ Saved at {when}</span>",
    "<span style='color:#ffb340'>Non ancora salvato</span>": "<span style='color:#ffb340'>Not saved yet</span>",
    "Si salva da solo a ogni scelta: puoi chiudere quando vuoi e riprendere da qui.\nProgressi: {v1}/{v2}\nFoto scelte: {v3}":
        "It saves by itself at every choice: you can quit any time and resume from here.\nProgress: {v1}/{v2}\nPhotos chosen: {v3}",
    "Elemento {pos} di {v1}": "Item {pos} of {v1}", "{pos} di {total}": "{pos} of {total}",
    "Durata: {d}": "Duration: {d}",
    "Stai guardando l'originale: clic per la versione modificata": "You're viewing the original: click for the edited version",
    "Stai guardando la versione modificata: clic per l'originale": "You're viewing the edited version: click for the original",
    "Modificata dopo il Sì: premi di nuovo ✓ per esportare questa versione": "Edited after Yes: press ✓ again to export this version",
    "Foto non ancora salvata: riprova tra un attimo": "Photo not saved yet: try again in a moment",
    "<span style='font-size:13px; font-weight:600; color:#f2f2f7;'>{done} di {v1} già fatte</span>":
        "<span style='font-size:13px; font-weight:600; color:#f2f2f7;'>{done} of {v1} done</span>",
    "Foto {v0} / {v1} · {who}": "Photo {v0} / {v1} · {who}",
    "Live disattivata: scegli Live nel menu della barra per farla partire col clic":
        "Live is off: choose Live in the bar menu to play it on click",
    "📷 {k} foto prese": "📷 {k} photos taken", "Clic sulla striscia per fermarti": "Click the strip to stop",
    " · <a style='color:#0a84ff' href='{url}'>Mappa</a>": " · <a style='color:#0a84ff' href='{url}'>Map</a>",
    "{v2} approvate · {v3} scartate · {v4} saltate": "{v2} approved · {v3} discarded · {v4} skipped",
    " · {v0} dai video": " · {v0} from videos", " · {v0} in “cancellare”": " · {v0} in “cancellare”",
    "Fotogramma {v0} / {v1}": "Frame {v0} / {v1}", "✓ già salvato": "✓ already saved",
    "F = salva come foto": "F = save as photo",
    "Nuova selezione": "New selection", "(proposta)": "(suggested)", "Come funziona": "How it works",
    "☁️ Questa cartella ha file su iCloud: ogni originale verrà scaricato quando lo apri (qualità sempre massima, ma con attesa). Per andare veloci usa una cartella su disco.":
        "☁️ This folder has files on iCloud: each original will be downloaded when you open it (always full quality, but with a wait). For speed, use a folder on disk.",
    "↻  Riprendi l'ultima sessione:  {v0}  →  {v1}": "↻  Resume the last session:  {v0}  →  {v1}",
    "Il lavoro salvato in questa cartella era danneggiato e non si è potuto leggere.\nÈ stato conservato come:\n{v0}\n\nSi riparte senza le scelte precedenti. I file in “cancellare” sono ancora lì.":
        "The saved work in this folder was damaged and could not be read.\nIt was kept as:\n{v0}\n\nStarting without the previous choices. The files in “cancellare” are still there.",
    "Scelta confermata: {v0}": "Choice confirmed: {v0}",
    "Scelta cambiata: {v0}   (Z annulla)": "Choice changed: {v0}   (Z undoes)",
    ", tasto ": ", key ",
    "Scelta non salvata: {e}": "Choice not saved: {e}",
    "Video non leggibile: {v0}": "Unreadable video: {v0}",
})


EN.update({
    "Non riesco a salvare il lavoro ({v0}). L'ultima scelta non è salvata.":
        "I can't save the work ({v0}). The last choice is not saved.",
    "{e} — e non riesco a rimettere a posto gli originali ({e2}): sono in “{TRASH_DIR}”:\n{v0}":
        "{e} — and I can't put the originals back ({e2}): they are in “{TRASH_DIR}”:\n{v0}",
    "Non riesco a salvare il lavoro ({v0}). Scegli un'altra cartella export.":
        "I can't save the work ({v0}). Choose another export folder.",
    "La cartella non è scrivibile: il lavoro si salva in\n{v0}":
        "The folder isn't writable: the work is saved in\n{v0}",
})


EN.update({
    "♥ Preferita: le copie vanno in export/Foto/Preferite": "♥ Favorite: the copies go to export/Foto/Preferite",
    "Export in ordine: {v0} copie spostate in Foto / Video con la data nel nome":
        "Export tidied: {v0} copies moved into Foto / Video with the date in the name",
    "{v0} copie in export non si sono potute rinominare: restano com'erano":
        "{v0} copies in export could not be renamed: they were left as they were",
})


HELP = {
    "it": """PULSANTI PRINCIPALI
✓ SÌ (Y o Invio): approva e copia nella cartella export: le foto in export/Foto, i video in export/Video. Ogni copia comincia con data e ora di scatto (es. 20240615_123456_IMG_0001.JPG), così la cartella è già in ordine cronologico.
   • Foto e panorami: copia identica dell'originale.
   • Live: salva come foto il fotogramma scelto sulla striscia (all'inizio, quello della fotocamera), a piena risoluzione.
   • Video: copia il video nella sottocartella "Video". Se hai preso delle foto con 📷, SÌ tiene solo quelle.
   • ＋ SÌ e video (Maiusc+Y): tiene le foto e copia anche il video.
✗ NO (N): scarta. Non copia niente.
↪ Salta (S): decidi dopo. A fine giro puoi rivedere le saltate.
🗑 Cancellare (X): sposta l'originale nella cartella "cancellare", dentro quella che stai guardando. Non cancella davvero: la svuoti tu a mano.
↩ Annulla (Z): torna all'ultima scelta. Se era un Sì, toglie anche i file copiati.
‹ Precedente (← o B) / Successivo › (→): rivedi anche le foto già decise o in "cancellare". Una nuova scelta sostituisce la vecchia e rimette a posto i file.
♡ Preferita (.): le preferite approvate finiscono in export/Foto/Preferite.
Le miniature in basso mostrano quelle prima e dopo: clic per andarci. Il pallino colorato indica la scelta fatta.
A destra c'è il pannello Info (ⓘ o I per nasconderlo): data, luogo, fotocamera, scatto e file.

LIVE
La Live si apre come foto. Sotto c'è la striscia dei fotogrammi: clic o trascina per scegliere, ↑ ↓ per spostarti di uno alla volta. Il riquadro bianco è la foto che SÌ salverà.
▶ Vedi Live (L): riguarda il video.   ↺ Originale (R): torna alla foto della fotocamera.
✨ Più nitida (P): cerca il fotogramma meno mosso lì vicino.

VIDEO
Clic sulla striscia (o Spazio, ↑ ↓) per fermarti sul fotogramma esatto.
Video: fermati sul fotogramma (pausa o clic sulla striscia), poi Regola / Ritaglia e OK: 📷 Prendi foto salva il fotogramma modificato (se l'avevi già preso, viene rifatto).
📷 Prendi foto (F): salva il fotogramma come foto. Compare un segno verde sulla striscia. Ne puoi prendere quante vuoi; Z annulla l'ultima.
⟲ Rivedi (V): dall'inizio, con l'audio.   ▶ / ⏸ (Spazio): riproduci o metti in pausa.

ZOOM
Il cursore in alto a sinistra sulla foto. Due dita su/giù sul trackpad (o pizzico) fanno zoom, trascina per spostarti, doppio clic per tornare a foto intera. Ogni foto si apre sempre intera.

INFO · REGOLA · RITAGLIA
Sono nel pannello a destra, in alto.
Info: le informazioni sulla foto.
Regola: come in Foto. Luce, Colore, Bianco e nero, Occhi rossi, Bilanciamento del bianco, Curve, Livelli, Definizione, Colore selettivo, Riduzione disturbo, Nitidezza, Vignettatura. AUTO = automatico. Come per Ritaglia, OK conferma le modifiche e Annulla le scarta (solo se qualcosa è cambiato); ↶ annulla quella regolazione; il cerchio blu accende o spegne le modifiche per confrontare. Puoi anche trascinare sulle miniature o aprire Opzioni.
✨ Bacchetta magica (in alto, accanto a ♡) – Luce e Colore automatici in un clic; di nuovo = via.
□|□ Confronta – mostra l'originale; "Ripristina originale" toglie tutte le modifiche.
Sfocatura: recupera nitidezza nelle foto mosse (AUTO la stima da sola).
Ritaglia: trascina angoli e lati del riquadro; Raddrizza, Verticale, Orizzontale, Capovolgi, Proporzioni. Conferma con OK (Invio) o annulla con Esc. Finché il ritaglio è aperto gli altri pulsanti aspettano.
Con ✓ Sì esporti la foto modificata o ritagliata (JPEG a qualità massima; l'originale non si tocca). "Annulla le modifiche", in fondo al pannello, la riporta com'era. □|□ confronta con l'originale.

IMPOSTAZIONI (⚙ in alto a destra)
Apri cartella: ① la cartella da guardare, ② la cartella export, poi Inizia.
Mostra: tutto / solo foto / solo video. Solo foto nasconde i video (restano foto, Live e panorami); solo video nasconde tutto il resto.
Export: cambia la cartella di destinazione. Mostra export: la apre nel Finder.
JPEG / PNG 16-bit: formato dei fotogrammi estratti da Live e video (JPEG va bene per la stampa).
Ora: fuso orario da scrivere nella data delle foto esportate.

SALVATAGGIO
Ogni scelta viene salvata subito in un file nascosto dentro la cartella che apri (.photoswipe-session.json). Riaprendo la cartella, l'app ti dice se il lavoro era a metà o completato e ti chiede se riprendere. I file su iCloud si scaricano da soli, e i 10 successivi in anticipo.""",
    "en": """MAIN BUTTONS
✓ YES (Y or Enter): approves and copies to the export folder: photos into export/Foto, videos into export/Video. Each copy starts with the capture date and time (e.g. 20240615_123456_IMG_0001.JPG), so the folder is already in chronological order.
   • Photos and panoramas: an exact copy of the original.
   • Live: saves the frame you picked on the strip as a photo (at first, the camera's pick), at full resolution.
   • Video: copies the video into the "Video" subfolder. If you took photos with 📷, YES keeps only those.
   • ＋ YES + video (Shift+Y): keeps the photos and also copies the video.
✗ NO (N): discards. Copies nothing.
↪ Skip (S): decide later. At the end you can review the skipped items.
🗑 Trash (X): moves the original into the "cancellare" folder, inside the folder you're browsing. Nothing is really deleted: you empty that folder yourself.
↩ Undo (Z): goes back to your last choice. If it was a Yes, it also removes the copied files.
‹ Previous (← or B) / Next › (→): review photos you already decided or put in "cancellare". A new choice replaces the old one and puts the files back in place.
♡ Favorite (.): approved favorites end up in export/Foto/Preferite.
The thumbnails at the bottom show the ones before and after: click to go there. The colored dot shows your choice.
The Info panel is on the right (ⓘ or I to hide it): date, place, camera, shot and file details.

LIVE
A Live opens as a photo. The frame strip below lets you choose: click or drag, ↑ ↓ to move one frame at a time. The white box is the photo that YES will save.
▶ Show Live (L): replays the video.   ↺ Original (R): back to the camera's photo.
✨ Sharper (P): looks for the least blurry frame nearby.

VIDEO
Click the strip (or Space, ↑ ↓) to stop on the exact frame.
Video: stop on the frame (pause or click the strip), then Adjust / Crop and OK: 📷 Take photo saves the edited frame (if you already took it, it is redone).
📷 Take photo (F): saves the frame as a photo. A green mark appears on the strip. You can take as many as you like; Z undoes the last one.
⟲ Replay (V): from the start, with sound.   ▶ / ⏸ (Space): play or pause.

ZOOM
The slider is at the top left of the photo. Two fingers up/down on the trackpad (or pinch) zoom, drag to move, double-click to fit the whole photo again. Every photo opens fully fitted.

INFO · ADJUST · CROP
They're in the panel on the right, at the top.
Info: information about the photo.
Adjust: as in Photos. Light, Color, Black & White, Red-eye, White balance, Curves, Levels, Definition, Selective color, Noise reduction, Sharpening, Vignette. AUTO = automatic. As with Crop, OK confirms the edits and Cancel discards them (only if something changed); ↶ resets that adjustment; the blue circle turns the edits on or off to compare. You can also drag onto the thumbnails or open Options.
✨ Magic wand (top bar, next to ♡) – automatic Light and Color in one click; again = off.
□|□ Compare – shows the original; "Restore original" removes all edits.
Blur: recovers sharpness in shaken photos (AUTO estimates it by itself).
Crop: drag the corners and sides of the frame; Straighten, Vertical, Horizontal, Flip, Aspect ratio. Confirm with OK (Enter) or cancel with Esc. While a crop is open, the other buttons wait.
With ✓ Yes you export the edited or cropped photo (JPEG at maximum quality; the original is never touched). "Discard edits", at the bottom of the panel, restores it. □|□ compares with the original.

SETTINGS (⚙ top right)
Open folder: ① the folder to browse, ② the export folder, then Start.
Show: all / photos only / videos only. Photos only hides videos (photos, Lives and panoramas stay); videos only hides everything else.
Export: change the destination folder. Show export: opens it in Finder.
JPEG / 16-bit PNG: format of the frames extracted from Lives and videos (JPEG is fine for printing).
Time: time zone to write into the dates of the exported photos.

SAVING
Every choice is saved right away in a hidden file inside the folder you open (.photoswipe-session.json). When you reopen that folder, the app tells you whether the work was half done or complete and asks whether to resume. iCloud files download by themselves, plus the next 10 in advance.""",
}
