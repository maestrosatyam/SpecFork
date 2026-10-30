"""SpecFork: find the meanings hiding in a function spec before a coding agent picks one.

Library use::

    import asyncio
    from specfork import Client

    async def main():
        async with Client() as sf:                    # settings from the environment / .env
            run = await sf.fork("Split a bill evenly among n people, rounded to cents.")
            for q in run.open_questions:
                print(q.text, [o.label for o in q.options])
            run = await sf.resolve(run, {q.id: q.options[0].id for q in run.open_questions})
            print(run.resolution.clarified_spec)
            print(sf.tests(run, module="billing"))

    asyncio.run(main())

Importing this package has no side effects (no environment reads, no network).
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("specfork")
except PackageNotFoundError:  # running from a source checkout without installation
    __version__ = "0.2.0.dev0"

from .api import Client, ForkError  # noqa: E402
from .types import Question, Run  # noqa: E402

__all__ = ["Client", "ForkError", "Run", "Question", "__version__"]
