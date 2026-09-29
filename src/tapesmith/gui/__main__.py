"""`python -m tapesmith.gui` öffnet die Web-Oberfläche im Standardbrowser (wie `p12 app` und `tapesmith`)."""

import sys

from tapesmith.webui.browser import main

sys.exit(main())
