# UI Notes

This repository uses a minimal server-rendered review interface exposed by FastAPI in [`app/api/main.py`](/home/user/Desktop/OpenMetaData/app/api/main.py).

That flow still works for lightweight review.

For the richer onboarding path, use the Next.js wizard under [`ui-next/`](/home/deepakrajb/Desktop/MD/OpenMetaData/ui-next). It asks schema-grounded business questions, writes answers back into the 5-file semantic bundle, and can publish the reviewed bundle into TAG plus trigger TAG semantic reindex.
