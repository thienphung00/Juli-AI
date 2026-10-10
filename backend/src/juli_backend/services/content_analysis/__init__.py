"""P15 content analysis of seller-uploaded videos and LIVE recordings (D24.19, D24.20).

Contract: ``fasttrack/contracts/p15-content-analysis.md``.

- ``config`` -- limits, models, paths, the default monthly cap (environment).
- ``storage`` -- temporary files on the VPS disk, the signed upload token, the sweep.
- ``uploads`` -- upload slots, chunks, the seller-facing view.
- ``media`` -- ffprobe / ffmpeg (read only, ``-f mov``, local files only).
- ``cuts`` -- scene cuts (port of the content engine's ``reference_analyze.py``).
- ``openai_media`` -- transcription and keyframe vision (OpenAI).
- ``scoring`` -- the ONE structured-output call over derived signals, the result.
- ``costs`` -- the per-shop monthly OpenAI cap.
- ``pipeline`` -- one analysis end to end; ``product_info`` -- product name /
  brand / images / SEO words.
- ``context`` -- best / weakest analyses as context for Juli soạn.

This ``__init__`` imports nothing so the routes and the drafter can import a
submodule without pulling the media stack.
"""
