self.ModelViewerElement = {
  dracoDecoderLocation: new URL('./draco/', import.meta.url).href,
  ktx2TranscoderLocation: new URL('./basis/', import.meta.url).href,
  meshoptDecoderLocation: new URL('./meshopt_decoder.js', import.meta.url).href,
};

await import('./model-viewer.min.js');
