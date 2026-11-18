# DollFit — GitHub / Render upload package

Upload the contents of this folder to the root of your `Ring123-ux/Rd` repository. The repository should contain `dollfit/`, `render.yaml`, and this README. Replace the existing files with the same names; do not upload this folder itself as one additional nested directory.

The full Chinese deployment instructions are in [dollfit/README.md](dollfit/README.md).

- Manual Render setup: Root Directory `dollfit`, Build `pip install -r requirements.txt && python -m deployment.assets restore`, Start `python -m deployment.start`.
- `render.yaml`: optional free test Blueprint. Free services lose runtime data on restart/sleep/redeploy. This is not permanent storage.
- `render.production.yaml`: optional paid 1 CPU / 2 GB + 10 GB persistent-disk example. It is not automatically selected or deployed.
- Provider keys and passwords must be set in Render Environment, never committed to this repository.
- Model/example binary parts are all at most 20,000,000 bytes, below GitHub's web upload per-file limit. Upload `dollfit/bundled/` in batches if the browser cannot handle a whole folder at once.
- The exported model uses the same floating-point trained weights, height + gender, no weight input. BJD accuracy remains unvalidated.
- The bundled 3D example is the verified 1,500,000-triangle textured/PBR result. New seller-service tasks request 1,500,000 faces. The clothing editor allows low, medium, or high quality at `1024x1536`.
