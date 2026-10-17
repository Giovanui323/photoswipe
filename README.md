# PhotoSwipe

Versione **1.2.4** — il numero è nel titolo della finestra.

Sfogli foto, panorami, Live e video della DJI Osmo Pocket 4 e scegli con **Sì / No / Salta**.
Quello che approvi viene **copiato** (mai spostato) nella cartella `export`, pronta da caricare
sul sito di stampa.

## Avvio (macOS)
Doppio clic su **`Avvia PhotoSwipe.command`**. La prima volta installa da solo ciò che serve.
Nella schermata iniziale: **①** scegli la cartella da guardare (es. `DCIM`, o tutta `dji pocket`;
vengono lette anche le sottocartelle), **②** la cartella export, poi **Inizia ▶**.
Oppure **Riprendi l'ultima sessione** per continuare da dove eri.

Il lavoro viene salvato a ogni scelta in un file nascosto **dentro la cartella che apri**
(`.photoswipe-session.json`). Se riapri una cartella già lavorata, l'app mostra se è a metà o
completata, quando l'avevi chiusa e quante ne avevi decise, e chiede se **riprendere** o
**ricominciare da capo** (il vecchio salvataggio viene rinominato, non cancellato).

## Interfaccia
Ispirata a Foto di macOS, con la scelta "alla Tinder":
- **sulla foto, in alto a sinistra**: il cursore dello **zoom** (foto e panorami).
- **in alto**: ‹ › precedente/successivo, ↩ annulla; al centro nome, data e
  posizione (es. "17 di 245"); a destra ♡ preferita, ⚙ **impostazioni** (cartella, export, filtro,
  formato, ora) e ? aiuto. Su Mac la barra del titolo è integrata (si trascina dallo spazio vuoto).
- **a destra, sempre aperto, il pannello Info**: giorno, luogo (coordinate GPS se presenti, con link
  "Apri nella mappa", nulla viene inviato in rete da solo), fotocamera, scatto (ƒ, tempo, ISO, mm),
  dimensioni, video (fps, bit, codec, bitrate), file e cartella; sotto, le foto prese dal video con
  📷 e il riepilogo della selezione.
  In basso a destra, le **foto prese dal video** in miniatura: clic = il video torna su quel
  fotogramma per rivederla, doppio clic = apre il file, ✕ = la toglie da export.
- **sotto la foto**: per Live e video la striscia dei fotogrammi con Vedi Live / Prendi foto / Più nitida;
  poi i pulsanti rotondi centrati: 🗑 No e cancella (X) · ✕ No (N) · ↪ Salta (S) · ✓ Sì (Y) ·
  ＋ Sì + video (⇧Y). Il cerchio pieno indica la scelta già fatta.
- **in fondo**: le miniature prima e dopo quella attuale (pallino = scelta fatta), clic per andarci.

## Tasti
| Tasto | Azione |
|---|---|
| **Y** o **Invio** | Sì: copia in export (Live: solo la foto) |
| **Maiusc+Y** | solo Live: Sì e copia anche il video in `export/Video` |
| **N** | No |
| **X** | sposta l'originale in `cancellare` (dentro la cartella che guardi); non cancella, Z lo rimette a posto |
| **S** | Salta (a fine giro puoi rivedere le saltate) |
| **Z** | Annulla l'ultima scelta (toglie anche i file copiati) |
| **C** | Cambia scena (Live e video) |
| **← / →** (Maiusc = 10) | fotogramma precedente / successivo |
| **P** | fotogramma più nitido vicino a quello scelto |
| **R** | torna alla foto scelta dalla fotocamera |
| **F** | prendi foto: salva subito il fotogramma che vedi |
| **V** | rivedi il video dall'inizio, con l'audio |
| **Spazio** | pausa / riproduci |
| rotella / doppio clic | zoom / adatta (foto e panorami) |

## Cosa fa con ogni tipo di file
- **Foto e panorami**: copia identica, byte per byte. I singoli scatti in `PANORAMA/` vengono
  saltati: il panorama finito è il JPG in `DJI_001` con lo stesso numero.
- **Live** (MP4 da 3 s): la fotocamera non salva una foto, solo il video. Con **Sì** viene estratto
  il fotogramma che la fotocamera mostra come foto (ricavato dall'anteprima `MISC/THM/*.SCR`),
  oppure quello che scegli con *Cambia scena*. Risoluzione piena (4K = 8,3 MP), dall'MP4 originale.
- **Video**: con **Sì** si copia il video in `export/Video`. Per tenere delle foto da un video usa
  **📷 Prendi foto (F)**: salva subito il fotogramma che vedi (es. `..._f0167.jpg`) e resti sul video,
  così puoi prenderne quante vuoi. Funziona anche sulle Live.
- Ignorati: `.LRF` (anteprime, usate solo per la riproduzione fluida), `MISC`, file `._` di macOS,
  doppioni con stesso nome e dimensione (es. copie in `Selezionati`).

## Qualità dei fotogrammi
- **JPEG qualità massima** (predefinito): conversione colore esatta di ffmpeg → JPEG qualità 100,
  colore pieno 4:4:4, profilo sRGB, EXIF con data e fuso dello scatto.
- **PNG 16-bit**: conserva i 10 bit del video (utile per cieli sfumati), file da ~40 MB.
- Limiti del file di partenza, non recuperabili: 8,3 MP (le verticali 5,3 MP), compressione HEVC
  della fotocamera, eventuale mosso. Formato massimo consigliato: 20×30 (le Live a 2 MP: 13×18,
  l'app lo segnala).

## iCloud
La qualità è sempre massima: per guardare un elemento l'app usa sempre l'**originale**. Se è su
iCloud lo scarica al momento (schermata con file, MB, secondi e percentuale stimata) e prepara in
anticipo, in automatico, i 10 successivi. Su una cartella su
disco (hard disk, cartella non sincronizzata) non si scarica nulla. La lettura della cartella non
scarica nulla. Consiglio: per lavorare veloci usa una cartella su disco.

## Ora degli scatti
L'orologio della fotocamera è cambiato durante il viaggio (alcuni file +02:00, altri −07:00):
l'app ricava il fuso di ogni file dall'ora UTC registrata nel video. Con il menu **Ora** puoi
forzare un fuso (es. UTC−7) per le date scritte nelle foto esportate.

## Sviluppo
```bash
.venv/bin/python -m pytest -q tests
```
