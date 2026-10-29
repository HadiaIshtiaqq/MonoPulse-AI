"use client";

import { useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import type Konva from "konva";
import { Ellipse, Image as KImage, Label, Layer, Line, Rect, RegularPolygon, Stage, Star, Tag, Text, Transformer } from "react-konva";
import { media } from "@/lib/api";
import type { El, ImageEl, Page, ShapeEl, TextEl } from "@/lib/design";

/** Images load once and are shared; crossOrigin so the canvas can still be exported. */
const cache = new Map<string, Promise<HTMLImageElement>>();
export const resolveSrc = (src: string) => (src.startsWith("/media/") ? media(src) : src);
export function loadImage(src: string): Promise<HTMLImageElement> {
  const url = resolveSrc(src);
  if (!cache.has(url)) {
    cache.set(url, new Promise((resolve, reject) => {
      const img = new window.Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = () => { cache.delete(url); reject(new Error(`couldn't load ${src}`)); };
      img.src = url;
    }));
  }
  return cache.get(url)!;
}
export async function preload(page: Page) {
  await Promise.allSettled(page.elements.filter((e): e is ImageEl => e.type === "image" && !!e.src).map((e) => loadImage(e.src)));
  if (typeof document !== "undefined" && document.fonts) {
    await Promise.allSettled(page.elements.filter((e): e is TextEl => e.type === "text")
      .map((e) => document.fonts.load(`${e.italic ? "italic " : ""}${e.bold ? "700 " : "400 "}${Math.round(e.fontSize)}px "${e.fontFamily}"`)));
  }
}

function useLoaded(src: string) {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    let live = true;
    setImg(null);
    if (src) loadImage(src).then((i) => live && setImg(i)).catch(() => live && setImg(null));
    return () => { live = false; };
  }, [src]);
  return img;
}

export type CanvasHandle = { exportPng: () => string; stage: () => Konva.Stage | null };

type Props = {
  /** Filled in with exportPng() etc. A prop, not a ref: next/dynamic doesn't pass refs through. */
  handle: React.MutableRefObject<CanvasHandle | null>;
  page: Page; width: number; height: number; scale: number; selectedId: string | null;
  onSelect: (id: string | null) => void; onChange: (el: El, commit: boolean) => void; onEditText: (el: TextEl) => void;
};

const SNAP = 10; // design pixels

export function Canvas({ handle, page, width, height, scale, selectedId, onSelect, onChange, onEditText }: Props) {
  const stageRef = useRef<Konva.Stage>(null);
  const trRef = useRef<Konva.Transformer>(null);
  const [guides, setGuides] = useState<{ v: number[]; h: number[] }>({ v: [], h: [] });
  const selected = page.elements.find((e) => e.id === selectedId);

  useImperativeHandle(handle, () => ({
    stage: () => stageRef.current,
    exportPng: () => {
      const stage = stageRef.current!;
      const tr = trRef.current;
      tr?.nodes([]);
      const url = stage.toDataURL({ pixelRatio: 1 / scale, mimeType: "image/png" });
      return url;
    },
  }));

  useEffect(() => {
    const tr = trRef.current, stage = stageRef.current;
    if (!tr || !stage) return;
    const node = selected && !selected.locked && !selected.hidden ? stage.findOne(`#${selected.id}`) : null;
    tr.nodes(node ? [node] : []);
    tr.getLayer()?.batchDraw();
  }, [selected, page]);

  // Snap a dragged layer's edges and centre to the page's edges and centre, and to other layers.
  const targets = useMemo(() => {
    const v = [0, width / 2, width], h = [0, height / 2, height];
    for (const e of page.elements) {
      if (e.id === selectedId || e.hidden || e.type === "text") continue;
      v.push(e.x, e.x + e.width / 2, e.x + e.width);
      h.push(e.y, e.y + e.height / 2, e.y + e.height);
    }
    return { v, h };
  }, [page, width, height, selectedId]);

  function snap(node: Konva.Node) {
    const box = node.getClientRect({ relativeTo: node.getLayer() ?? undefined });
    const xs = [box.x, box.x + box.width / 2, box.x + box.width], ys = [box.y, box.y + box.height / 2, box.y + box.height];
    const gv: number[] = [], gh: number[] = [];
    let dx = 0, dy = 0;
    for (const t of targets.v) for (const x of xs) if (!dx && Math.abs(t - x) < SNAP) { dx = t - x; gv.push(t); }
    for (const t of targets.h) for (const y of ys) if (!dy && Math.abs(t - y) < SNAP) { dy = t - y; gh.push(t); }
    node.x(node.x() + dx);
    node.y(node.y() + dy);
    setGuides({ v: gv, h: gh });
  }

  function common(e: El) {
    return {
      id: e.id, key: e.id, x: e.x, y: e.y, rotation: e.rotation, opacity: e.opacity, visible: !e.hidden,
      draggable: !e.locked && e.id === selectedId,
      onMouseDown: (ev: Konva.KonvaEventObject<MouseEvent | TouchEvent>) => { ev.cancelBubble = true; if (!e.locked) onSelect(e.id); },
      onTouchStart: (ev: Konva.KonvaEventObject<TouchEvent>) => { ev.cancelBubble = true; if (!e.locked) onSelect(e.id); },
      onDragMove: (ev: Konva.KonvaEventObject<DragEvent>) => snap(ev.target),
      onDragEnd: (ev: Konva.KonvaEventObject<DragEvent>) => { setGuides({ v: [], h: [] }); onChange({ ...e, x: ev.target.x(), y: ev.target.y() } as El, true); },
      onTransformEnd: (ev: Konva.KonvaEventObject<Event>) => {
        const n = ev.target;
        const sx = n.scaleX(), sy = n.scaleY();
        n.scaleX(1); n.scaleY(1);
        if (e.type === "text") {
          onChange({ ...e, x: n.x(), y: n.y(), rotation: n.rotation(), width: Math.max(40, e.width * sx), fontSize: Math.max(8, e.fontSize * sy) }, true);
        } else if (e.type === "circle" || e.type === "star" || e.type === "triangle") {
          onChange({ ...e, rotation: n.rotation(), width: Math.max(10, e.width * sx), height: Math.max(10, e.height * sy),
            x: n.x() - (e.width * sx) / 2, y: n.y() - (e.height * sy) / 2 } as El, true);
        } else {
          onChange({ ...e, x: n.x(), y: n.y(), rotation: n.rotation(), width: Math.max(10, e.width * sx), height: Math.max(e.type === "line" ? 0 : 10, e.height * sy) } as El, true);
        }
      },
    };
  }

  return (
    <Stage ref={stageRef} width={width * scale} height={height * scale} scaleX={scale} scaleY={scale}
      onMouseDown={(ev) => { if (ev.target === ev.target.getStage()) onSelect(null); }}
      onTouchStart={(ev) => { if (ev.target === ev.target.getStage()) onSelect(null); }}
      style={{ boxShadow: "0 10px 40px rgba(15,23,42,0.18)", background: page.background }}>
      <Layer>
        <Rect x={0} y={0} width={width} height={height} fill={page.background} listening={true} name="page"
          onMouseDown={() => onSelect(null)} onTouchStart={() => onSelect(null)} />
        {page.elements.map((e) => {
          if (e.type === "text") return <TextLayer key={e.id} el={e} common={common(e)} onEdit={() => onEditText(e)} />;
          if (e.type === "image") return <ImageLayer key={e.id} el={e} common={common(e)} />;
          return <ShapeLayer key={e.id} el={e} common={common(e)} />;
        })}
        {guides.v.map((x, i) => <Line key={`v${i}`} points={[x, 0, x, height]} stroke="#FF3EA5" strokeWidth={2 / scale} dash={[8 / scale, 6 / scale]} listening={false} />)}
        {guides.h.map((y, i) => <Line key={`h${i}`} points={[0, y, width, y]} stroke="#FF3EA5" strokeWidth={2 / scale} dash={[8 / scale, 6 / scale]} listening={false} />)}
        <Transformer ref={trRef} rotateEnabled keepRatio={selected?.type === "image"} borderStroke="#7C5CFF" anchorStroke="#7C5CFF"
          anchorFill="#FFFFFF" anchorSize={10} anchorCornerRadius={5} rotationSnaps={[0, 45, 90, 135, 180, 225, 270, 315]}
          enabledAnchors={selected?.type === "text" ? ["middle-left", "middle-right", "top-left", "top-right", "bottom-left", "bottom-right"] : undefined}
          boundBoxFunc={(oldBox, newBox) => (newBox.width < 8 || newBox.height < 4 ? oldBox : newBox)} />
      </Layer>
    </Stage>
  );
}

function TextLayer({ el, common, onEdit }: { el: TextEl; common: any; onEdit: () => void }) {
  const style = `${el.italic ? "italic " : ""}${el.bold ? "bold" : "normal"}`.trim();
  const shown = el.uppercase ? el.text.toUpperCase() : el.text;
  // A Label: the text, with an optional highlight box behind it that always fits the text.
  return (
    <Label {...common} onDblClick={onEdit} onDblTap={onEdit}>
      {el.highlight ? <Tag fill={el.highlight} cornerRadius={el.fontSize * 0.2} /> : null}
      <Text text={shown} width={el.width} fontFamily={el.fontFamily} fontSize={el.fontSize} fontStyle={style}
        textDecoration={el.underline ? "underline" : ""} fill={el.fill} align={el.align} lineHeight={el.lineHeight} letterSpacing={el.letterSpacing}
        padding={el.highlight ? el.fontSize * 0.25 : 0}
        shadowColor={el.shadow ? "rgba(0,0,0,0.45)" : undefined} shadowBlur={el.shadow ? el.fontSize * 0.25 : 0}
        shadowOffsetY={el.shadow ? el.fontSize * 0.06 : 0} />
    </Label>
  );
}

function ImageLayer({ el, common }: { el: ImageEl; common: any }) {
  const img = useLoaded(el.src);
  if (!img) return <Rect {...common} width={el.width} height={el.height} fill="#E5E7EB" cornerRadius={el.cornerRadius} />;
  if (el.fit === "contain") {  // the whole picture inside the box (logos), centred
    const k = Math.min(el.width / img.width, el.height / img.height);
    const w = img.width * k, h = img.height * k;
    return <KImage {...common} image={img} width={w} height={h} offsetX={-(el.width - w) / 2} offsetY={-(el.height - h) / 2} />;
  }
  let crop: { x: number; y: number; width: number; height: number } | undefined;
  if (el.fit === "cover") {  // fills the box, trimmed like a photo frame
    const k = Math.max(el.width / img.width, el.height / img.height);
    const cw = el.width / k, ch = el.height / k;
    crop = { x: (img.width - cw) / 2, y: (img.height - ch) / 2, width: cw, height: ch };
  }
  return (
    <KImage {...common} image={img} crop={crop} width={el.width} height={el.height} cornerRadius={el.cornerRadius}
      scaleX={el.flipX ? -1 : 1} offsetX={el.flipX ? el.width : 0} />
  );
}

function fillProps(el: ShapeEl) {
  if (!el.gradient) return { fill: el.fill };
  const { from, to, angle } = el.gradient;
  const [sx, sy, ex, ey] = angle === 90 ? [0, 0, 0, el.height] : angle === 270 ? [0, el.height, 0, 0] : angle === 180 ? [el.width, 0, 0, 0] : [0, 0, el.width, 0];
  return { fillLinearGradientStartPoint: { x: sx, y: sy }, fillLinearGradientEndPoint: { x: ex, y: ey }, fillLinearGradientColorStops: [0, from, 1, to] };
}

function ShapeLayer({ el, common }: { el: ShapeEl; common: any }) {
  const stroke = { stroke: el.stroke || undefined, strokeWidth: el.strokeWidth };
  if (el.type === "rect") return <Rect {...common} width={el.width} height={el.height} cornerRadius={el.cornerRadius} {...fillProps(el)} {...stroke} />;
  if (el.type === "line") return <Line {...common} points={[0, 0, el.width, 0]} stroke={el.stroke || el.fill} strokeWidth={el.strokeWidth || 6} lineCap="round" hitStrokeWidth={30} />;
  const centred = { ...common, x: el.x + el.width / 2, y: el.y + el.height / 2 };
  if (el.type === "circle") return <Ellipse {...centred} radiusX={el.width / 2} radiusY={el.height / 2} {...fillProps(el)} {...stroke} />;
  if (el.type === "triangle") return <RegularPolygon {...centred} sides={3} radius={Math.min(el.width, el.height) / 2} {...fillProps(el)} {...stroke} />;
  return <Star {...centred} numPoints={5} innerRadius={Math.min(el.width, el.height) / 4} outerRadius={Math.min(el.width, el.height) / 2} {...fillProps(el)} {...stroke} />;
}
