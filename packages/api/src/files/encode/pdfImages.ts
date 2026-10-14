import path from 'path';
import type { TextItem } from 'pdfjs-dist/types/src/display/api';

/** pdfjs needs this on disk to lay out/draw standard (non-embedded) fonts like Helvetica —
 *  without it, `getDocument` throws `UnknownErrorException` on any PDF that uses one. */
const STANDARD_FONT_DATA_URL = `${path.join(
  path.dirname(require.resolve('pdfjs-dist/package.json')),
  'standard_fonts',
)}/`;

/** Balances visual clarity against the number of visual tokens each page costs the model;
 *  mirrors the DPI tradeoff a PDF viewer makes when rendering for screen rather than print. */
const PDF_IMAGE_SCALE = 1;

export interface PdfPageContent {
  pageNumber: number;
  text: string;
  imageBase64: string;
}

/**
 * Renders each page of a PDF to a PNG image and extracts its text.
 *
 * For models that can see images but whose server rejects a native file/document content
 * block (confirmed for vLLM: "Unsupported chat content part type: 'file'"), this is the
 * alternative: the page's exact text (for citations, fine print, multi-column reflow) and
 * its visual layout (figures, charts, tables) both reach the model, each where it actually
 * appears in the document, instead of losing one or the other.
 */
export async function renderPdfPagesWithText(buffer: Buffer): Promise<PdfPageContent[]> {
  const [{ getDocument }, { createCanvas }] = await Promise.all([
    import('pdfjs-dist/legacy/build/pdf.mjs'),
    import('@napi-rs/canvas'),
  ]);

  const data = new Uint8Array(buffer);
  const pdf = await getDocument({ data, standardFontDataUrl: STANDARD_FONT_DATA_URL }).promise;

  const pages: PdfPageContent[] = [];
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);

    const textContent = await page.getTextContent();
    const text = textContent.items
      .map((item) => ('str' in item ? (item as TextItem).str : ''))
      .join(' ')
      .trim();

    const viewport = page.getViewport({ scale: PDF_IMAGE_SCALE });
    const canvas = createCanvas(Math.ceil(viewport.width), Math.ceil(viewport.height));
    const context = canvas.getContext('2d');
    await page.render({
      canvas: canvas as unknown as HTMLCanvasElement,
      canvasContext: context as unknown as CanvasRenderingContext2D,
      viewport,
    }).promise;

    pages.push({
      pageNumber,
      text,
      imageBase64: canvas.toBuffer('image/png').toString('base64'),
    });
  }

  return pages;
}
