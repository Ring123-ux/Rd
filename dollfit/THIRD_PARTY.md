# Sources and model provenance

- Body measurement architecture: https://github.com/Harshalnikumbh/bodym-measurement-estimation, pinned upstream commit `91970223544a4141dc1d8ac80b2e15e29c1fd1a6`.
- The local height/gender model removed weight and was retrained in the earlier local project. Original trained checkpoint SHA-256: `d8961a9ae1e913acc9d59fc51200c01fe4524991e9e08a5a4bd21b22a4f50d26`. This package includes its FP32 ONNX export and only global normalization metadata, not the original training photos, subject tables, or training environment.
- Foreground segmentation U2NETP: https://github.com/danielgatis/rembg and https://github.com/xuebinqin/U-2-Net . Bundled ONNX source: https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx . SHA-256 `309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8`.
- model-viewer 4.0.0: https://github.com/google/model-viewer . It is loaded from jsDelivr and provides interactive GLB browsing; it is not a reconstruction or measurement engine.
- Font licenses are retained under `assets/fonts/` alongside the original website font assets.
- The 3D example is the already-generated purchased-service result, not a new generation or a claim about body-measurement accuracy. This bundle does not grant additional vendor/API/dataset commercialization rights; retain and check the terms applicable to the source materials and purchased services before commercial redistribution.
