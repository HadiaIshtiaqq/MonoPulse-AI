import { media } from "@/lib/api";

/** Paste shortcut label for this computer. */
export const pasteKey = () => (typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘V" : "Ctrl+V");

async function imageBlob(url: string): Promise<Blob> {
  const res = await fetch(media(url), { cache: "no-store" });
  if (!res.ok) throw new Error("Couldn't load the image.");
  return res.blob();
}

/** Put a rendered post image on the clipboard, so pasting into a post box attaches it. */
export async function copyImage(url: string): Promise<boolean> {
  if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write) return false;
  try {
    // Pass the blob as a promise: Safari only allows clipboard writes started inside the click.
    await navigator.clipboard.write([new ClipboardItem({ "image/png": imageBlob(url) })]);
    return true;
  } catch {
    return false;
  }
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Save every image of a post (all slides of a carousel) to the computer. */
export async function downloadAll(urls: string[], baseName: string): Promise<void> {
  for (const [i, url] of urls.entries()) {
    const blob = await imageBlob(url);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = urls.length > 1 ? `${baseName}-${i + 1}.png` : `${baseName}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }
}

/** Whether this device can hand images to other apps (phones, and Chrome/Edge on Windows). */
export function canShareFiles(): boolean {
  if (typeof navigator === "undefined" || !navigator.canShare) return false;
  try {
    return navigator.canShare({ files: [new File([new Uint8Array(1)], "post.png", { type: "image/png" })] });
  } catch {
    return false;
  }
}

/** Open the device's share sheet with the post's images and caption. */
export async function shareToApp(urls: string[], caption: string, baseName: string): Promise<void> {
  const files = await Promise.all(urls.map(async (u, i) => new File([await imageBlob(u)], `${baseName}-${i + 1}.png`, { type: "image/png" })));
  await navigator.share({ files, text: caption });
}
