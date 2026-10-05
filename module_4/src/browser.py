"""Chrome driver used by the scraper.

Grad Cafe sits behind Cloudflare, so pages are read out of a Chrome window
that the user has already cleared by hand. The window is driven with
AppleScript through ``osascript``.

Everything that talks to Chrome lives in :class:`ChromeBrowser`. The scraper
only ever calls the small interface below, which is why the tests can pass a
fake browser and never launch anything:

``navigate(url)``, ``current_html()``, ``first_result_id()``,
``recycle_tab(url)``, ``ensure_window(url)``, ``title()``
"""

import subprocess
import time

#: Seconds AppleScript waits before giving up on Chrome. The default of 60 is
#: too short once Chrome has been running for hours.
APPLE_EVENT_TIMEOUT = 300


class BrowserError(RuntimeError):
    """Raised when Chrome cannot be driven or does not answer."""


class ChromeBrowser:
    """Drive the frontmost Chrome window through AppleScript.

    :param timeout: seconds to allow each Apple Event.
    :param runner: callable used to run ``osascript``; injected by tests.
        Defaults to :func:`subprocess.run`.
    :param sleeper: callable used to wait between retries; injected by tests.
        Defaults to :func:`time.sleep`.
    """

    def __init__(self, timeout=APPLE_EVENT_TIMEOUT, runner=None, sleeper=None):
        self.timeout = timeout
        self._run = runner or subprocess.run
        self._sleep = sleeper or time.sleep

    def _osascript(self, script):
        """Run *script* with ``osascript`` and return the completed process."""
        return self._run(["osascript", "-e", script], capture_output=True, text=True)

    def _tell(self, body, action):
        """Run an AppleScript ``tell`` block, raising :class:`BrowserError`.

        :param body: the AppleScript body to wrap in a timeout block.
        :param action: short description used in the error message.
        :returns: the process stdout.
        """
        script = f'with timeout of {self.timeout} seconds\n{body}\nend timeout\n'
        result = self._osascript(script)
        if result.returncode != 0:
            raise BrowserError(f"{action} failed: {result.stderr.strip()}")
        return result.stdout

    def run_js(self, js, attempts=3):
        """Evaluate JavaScript in the active tab and return its result.

        Transient Apple Event failures are retried rather than ending a long
        run.

        :param js: the JavaScript expression.
        :param attempts: how many times to try before giving up.
        :returns: the expression's result as text.
        :raises BrowserError: when every attempt fails.
        """
        script = (
            f'with timeout of {self.timeout} seconds\n'
            '  tell application "Google Chrome"\n'
            '    tell active tab of front window\n'
            f'      execute javascript "{js}"\n'
            "    end tell\n"
            "  end tell\n"
            "end timeout\n"
        )
        last_error = ""
        for attempt in range(1, attempts + 1):
            result = self._osascript(script)
            if result.returncode == 0:
                return result.stdout
            last_error = result.stderr.strip()
            if attempt < attempts:
                self._sleep(2 * attempt)
        raise BrowserError(f"osascript failed after {attempts} tries: {last_error}")

    def title(self):
        """Return the active tab's document title."""
        return self.run_js("document.title")

    def current_html(self):
        """Return the results table plus the Next link from the active tab.

        The full document is roughly 900KB and pushing that through an Apple
        Event is what causes timeouts; the table plus one anchor is about
        60KB and holds everything the parser needs.

        :returns: an HTML fragment.
        """
        return self.run_js(
            "(function(){"
            "var t=document.querySelector('table');"
            "var n=Array.from(document.getElementsByTagName('a')).filter("
            "function(a){return a.href.indexOf('cursor=')>-1"
            " && a.textContent.indexOf('Next')>-1;});"
            "return (t?t.outerHTML:'')+(n.length?n[n.length-1].outerHTML:'');"
            "})()"
        )

    def first_result_id(self):
        """Return the id of the first ``/result/`` link, or ``''`` if none yet."""
        return self.run_js(
            "(function(){"
            "var a=Array.from(document.getElementsByTagName('a')).filter("
            "function(x){return x.href.indexOf('/result/')>-1;});"
            "return a.length?a[0].href.split('/result/')[1]:'';"
            "})()"
        ).strip()

    def navigate(self, url):
        """Point the active tab at *url*.

        :param url: the URL to open.
        :raises BrowserError: when Chrome refuses.
        """
        self._tell(
            '  tell application "Google Chrome"\n'
            f'    set URL of active tab of front window to "{url}"\n'
            "  end tell",
            "navigation",
        )

    def recycle_tab(self, url):
        """Open a fresh tab at *url* and close the one it replaces.

        Navigating a single tab thousands of times leaks memory in the
        renderer until Chrome stops answering Apple Events. A new tab starts
        clean and keeps the Cloudflare clearance cookie. Exactly one tab is
        closed, by reference, because closing the last tab in a window closes
        the window and every later call then fails.

        :param url: the URL the new tab should open.
        :raises BrowserError: when Chrome refuses.
        """
        self._tell(
            '  tell application "Google Chrome"\n'
            "    set theWindow to front window\n"
            "    set oldTab to active tab of theWindow\n"
            f'    make new tab at end of tabs of theWindow with properties {{URL:"{url}"}}\n'
            "    set active tab index of theWindow to (count of tabs of theWindow)\n"
            "    try\n"
            "      close oldTab\n"
            "    end try\n"
            "  end tell",
            "tab recycle",
        )

    def ensure_window(self, url):
        """Reopen a Chrome window at *url* when none is left.

        Failures are swallowed: this is a recovery step and the caller
        retries anyway.

        :param url: the URL to open in the new window.
        """
        script = (
            f'with timeout of {self.timeout} seconds\n'
            '  tell application "Google Chrome"\n'
            "    if (count of windows) is 0 then\n"
            "      make new window\n"
            f'      set URL of active tab of front window to "{url}"\n'
            "    end if\n"
            "    activate\n"
            "  end tell\n"
            "end timeout\n"
        )
        self._osascript(script)
