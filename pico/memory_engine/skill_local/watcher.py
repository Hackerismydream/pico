"""Background filesystem watcher for :class:`SkillRegistry`.

Watches the workspace skill tree and invalidates the registry cache
per-source when SKILL.md files appear / change / disappear. This is
what lets a hand-edited ``<workspace>/skills/foo/SKILL.md`` surface to
the in-process selector without a process restart — complementing the
existing :meth:`SkillService.invalidate_skill_cache` hook used by other
in-process writers.

Design notes:

  - **Explicit lifecycle.** The watcher runs in a daemon thread so an
    exceptional process exit is not converted into an indefinite hang, but
    daemon status is not a cleanup mechanism. Hosts that construct a catalog
    must call :meth:`stop` before interpreter finalization. ``watchfiles`` owns
    native watcher state that is unsafe to race with CPython teardown.
  - **Workspace-only** scope. Builtin / external are read-only mirrors
    in this codebase; the builtin layer in particular can carry ~80K
    files and would blow past Linux's default ``fs.inotify.max_user_watches``
    if recursively watched. If a use case for watching those appears
    later, accept extra roots through ``__init__``.
  - ``watchfiles`` is a hard dependency, but :meth:`start` still
    catches ``ImportError`` defensively (so a stripped / partial install
    degrades to manual-invalidation mode instead of crashing) — it
    logs once and returns ``False`` in that case.
  - Runtime event handling is best-effort: an exception in the watcher thread
    is logged and leaves the registry in manual-invalidation mode. Shutdown is
    different: :meth:`stop` fails explicitly if the thread cannot be joined,
    rather than dropping the only handle to a live native watcher.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from pathlib import Path, PurePath

log = logging.getLogger(__name__)


def _is_skill_md(_change, path: str) -> bool:
    """``watchfiles`` filter — only SKILL.md events are interesting.

    Uses :class:`PurePath` so the basename check is cross-platform
    without relying on which separator (``/`` vs. ``\\``) watchfiles
    happens to return on a given OS / version. ``PurePath`` picks
    ``PurePosixPath`` on Linux/macOS and ``PureWindowsPath`` on
    Windows automatically.
    """
    return PurePath(path).name == "SKILL.md"


class SkillFileWatcher:
    """Daemon-thread watcher that pipes file events into the registry.

    Lifecycle:

      - :meth:`start` is idempotent and never raises. Returns ``True``
        iff a new daemon thread is now running.
      - :meth:`stop` signals and joins the thread. It is idempotent, but raises
        :class:`RuntimeError` if called by the watcher thread itself or if the
        native watcher does not terminate before the timeout.
    """

    def __init__(
        self,
        roots: Iterable[Path],
        on_change: Callable[[str], None],
        resolve_source: Callable[[Path], str | None],
    ):
        # Filter out None / missing entries so callers can hand us
        # optional layer roots (e.g. ``external_skills``) without
        # pre-checking.
        self._roots = [r for r in roots if r is not None and r.exists()]
        self._on_change = on_change
        self._resolve_source = resolve_source
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Start the daemon watcher thread.

        Returns ``True`` when a thread was just started. Returns
        ``False`` (and stays a no-op) when:

          - watchfiles is not installed,
          - no watchable roots exist on disk,
          - a watcher thread is already running.
        """
        if self._thread is not None and self._thread.is_alive():
            return False
        if not self._roots:
            log.debug("SkillFileWatcher: no existing roots, not starting")
            return False
        try:
            import watchfiles  # noqa: F401
        except ImportError:
            log.info(
                "watchfiles not installed — SkillRegistry auto-refresh "
                "disabled. Reinstall pico-harness with the official Pico "
                "installer to enable it."
            )
            return False

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="SkillFileWatcher",
            daemon=True,
        )
        self._thread.start()
        log.debug(
            "SkillFileWatcher started on %d root(s): %s",
            len(self._roots),
            [str(r) for r in self._roots],
        )
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the watcher to exit and require a successful join.

        Safe to call repeatedly and safe when no watcher was started. A live
        watcher handle is retained when joining fails so a later Runtime close
        can retry; the method never reports success while a native watcher is
        still running.
        """
        self._stop.set()
        thread = self._thread
        if thread is None:
            return
        if thread is threading.current_thread():
            raise RuntimeError(
                "SkillFileWatcher.stop() cannot join the watcher thread from itself",
            )
        if thread.is_alive():
            thread.join(timeout=timeout)
        if thread.is_alive():
            raise RuntimeError(
                f"SkillFileWatcher did not stop within {timeout:.1f}s",
            )
        self._thread = None

    # ------------------------------------------------------------------

    def _run(self) -> None:
        # Import inside the thread so ``start()``'s ImportError check is
        # the single source of truth for "is the dep present".
        from watchfiles import watch

        try:
            for changes in watch(
                *self._roots,
                watch_filter=_is_skill_md,
                stop_event=self._stop,
                # Daemon thread inside a larger app — don't let Ctrl+C
                # in the main thread synthesize KeyboardInterrupt here.
                raise_interrupt=False,
            ):
                # Collapse the batch to distinct sources before firing
                # callbacks so a multi-file save (e.g. git checkout
                # restoring many SKILL.md at once) costs one invalidate
                # per source rather than per file.
                dirty: set[str] = set()
                for _change, raw_path in changes:
                    source = self._resolve_source(Path(raw_path))
                    if source is not None:
                        dirty.add(source)
                for source in dirty:
                    try:
                        self._on_change(source)
                    except Exception:
                        # One bad callback must not kill the watcher —
                        # the next batch may target a different source.
                        log.exception(
                            "SkillFileWatcher on_change failed for source=%s",
                            source,
                        )
        except Exception:
            # Any other failure (watchfiles internal error, FS gone,
            # etc.) leaves the thread dead but the registry usable in
            # manual-invalidation mode.
            log.exception("SkillFileWatcher crashed; auto-refresh disabled until restart")
