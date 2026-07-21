# Image inputs

The real book-preparation pass will replace the tiny PBM smoke-test card with
one 16:9 PNG for every scene. The expected production files will be named for
their scenes, for example:

- `workshop_opening.png`
- `ada_promise.png`

`placeholder.pbm` exists only so the automated spec/audio integration test has
a valid local image. It is not a production visual.

The image path is intentionally required and local. Remote image URLs and paths
outside the project directory are rejected.
