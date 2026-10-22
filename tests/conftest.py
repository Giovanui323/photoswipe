"""I test controllano i testi in italiano: la lingua dell'interfaccia viene fissata qui."""
import os

os.environ.setdefault("PHOTOSWIPE_LANG", "it")

# miniature in cache: in una cartella temporanea, non nella cache vera dell'utente
import tempfile  # noqa: E402

os.environ.setdefault("PHOTOSWIPE_THUMB_CACHE", tempfile.mkdtemp(prefix="photoswipe-thumbs-"))

# log dei test a parte: non si mescolano con quelli dell'app vera (~/Library/Logs/PhotoSwipe)
os.environ.setdefault("PHOTOSWIPE_LOG_DIR", tempfile.mkdtemp(prefix="photoswipe-logs-"))
