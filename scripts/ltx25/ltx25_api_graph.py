#!/usr/bin/env python3
"""LTX-2.5 FLF2V workflow'unu ComfyUI POST /prompt API formatına çevirir.

Arka plan — partner node (subgraph) /prompt'ta ÇALIŞMAZ
-------------------------------------------------------
ComfyUI sunucusu ``POST /prompt`` gövdesindeki her düğümün ``class_type``
alanını ``nodes.NODE_CLASS_MAPPINGS`` üzerinden doğrular
(``execution.py::validate_prompt`` → ``missing_node_type`` hatası). Subgraph
"partner" düğümleri (class_type = UUID, örn. ``cf70afc4-5a03-47ce-8210-
734b1de6c6bc``) yalnızca frontend (litegraph) tarafında var olan yapay
düğümlerdir; sunucuda böyle bir sınıf yoktur ve ``definitions.subgraphs``
sunucuya hiç iletilmez. Bu yüzden UI formatındaki workflow, kuyruğa
girmeden önce frontend'de gerçek düğümlere açılır (expand). Bu modül aynı
açma işlemini çevrimdışı ve deterministik olarak yapar:

  1. UI JSON'daki partner düğümünü bulur (class_type bir subgraph UUID'si).
  2. ``definitions.subgraphs`` tanımındaki iç düğümleri API düğümlerine
     çevirir (widget sıraları ComfyUI a7b1d39d kaynak şemalarıyla pinli).
  3. Subgraph giriş slotlarını partner widget değerleri / dış bağlantılarla
     eşler, subgraph çıkışını partnerin çıktı bağlantısına bağlar.

Kullanım
--------
    from ltx25_api_graph import build_flf2v_graph, build_api_payload

    graph = build_flf2v_graph(
        prompt="...",
        first_image="first.png",       # ComfyUI input/ dizinindeki dosya adı
        last_image="last.png",
        duration_sec=5, width=1280, height=720, fps=24,
        seed=873293130933086,
    )
    payload = build_api_payload(graph, client_id="...")   # POST /prompt gövdesi

    import urllib.request, json
    req = urllib.request.Request("http://127.0.0.1:8188/prompt",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")

GPU gerektirmez; ürettiği graph sözlüğü tamamen JSON-serializable'dır.
"""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

__all__ = [
    "load_template",
    "expand_ui_workflow",
    "build_flf2v_graph",
    "build_api_payload",
    "LTX25_FLF2V_SUBGRAPH_ID",
    "API_NODE_CLASSES",
]

# Resmî "First & Last Frame to Video (LTX-2.5)" şablonundaki partner düğümün
# class_type'ı (subgraph UUID'si — frontend-only, /prompt'a gönderilemez).
LTX25_FLF2V_SUBGRAPH_ID = "cf70afc4-5a03-47ce-8210-734b1de6c6bc"

# Modülün ürettiği graph'larda görünebilecek TÜM class_type'lar. Liste,
# Comfy-Org/ComfyUI @ a7b1d39d342d102f305797fb5ba12dc304d9c1f5 kaynak
# şemalarından (nodes.py + comfy_extras) doğrulanmıştır; testler, üretilen
# graph'ın yalnızca gerçek düğüm sınıfları içerdiğini bu sabitle kontrol eder.
API_NODE_CLASSES = frozenset(
    {
        # core (nodes.py, v1)
        "LoadImage", "SaveVideo", "UNETLoader", "VAELoader", "CLIPLoader",
        "CLIPTextEncode", "VAEDecodeTiled",
        # comfy_extras/nodes_lt.py
        "EmptyLTXVLatentVideo", "LTXVAddGuide", "LTXVCropGuides",
        "LTXVConditioning", "LTXVConcatAVLatent", "LTXVSeparateAVLatent",
        "LTXVDualCFGGuider", "LTXVPreprocess",
        # comfy_extras/nodes_lt_audio.py
        "LTXVEmptyLatentAudio", "LTXVAudioVAEDecode",
        # comfy_extras/nodes_custom_sampler.py
        "RandomNoise", "SamplerEulerAncestral", "ManualSigmas",
        "SamplerCustomAdvanced",
        # comfy_extras/nodes_post_processing.py
        "ResizeImageMaskNode",
        # comfy_extras/nodes_images.py
        "GetImageSize",
        # comfy_extras/nodes_video.py
        "CreateVideo",
        # comfy_extras/nodes_primitive.py
        "PrimitiveInt", "PrimitiveBoolean", "PrimitiveStringMultiline",
        # comfy_extras/nodes_math.py
        "ComfyMathExpression",
        # comfy_extras/nodes_logic.py
        "ComfySwitchNode",
        # comfy_extras/nodes_textgen.py
        "TextGenerateLTX2Prompt",
        # comfy_extras/nodes_preview_any.py
        "PreviewAny",
    }
)

# OUTPUT_NODE sınıfları (sunucu /prompt'un en az bir çıktı düğümü ister).
_OUTPUT_NODES = frozenset({"SaveVideo", "PreviewAny"})

# RETURN_TYPES uzunlukları (bağlantı bütünlüğü denetimi için; aynı kaynak pinli).
_OUTPUT_COUNT = {
    "LoadImage": 2, "SaveVideo": 1, "UNETLoader": 1, "VAELoader": 1,
    "CLIPLoader": 1, "CLIPTextEncode": 1, "VAEDecodeTiled": 1,
    "EmptyLTXVLatentVideo": 1, "LTXVAddGuide": 3, "LTXVCropGuides": 3,
    "LTXVConditioning": 2, "LTXVConcatAVLatent": 1, "LTXVSeparateAVLatent": 2,
    "LTXVDualCFGGuider": 1, "LTXVPreprocess": 1, "LTXVEmptyLatentAudio": 1,
    "LTXVAudioVAEDecode": 1, "RandomNoise": 1, "SamplerEulerAncestral": 1,
    "ManualSigmas": 1, "SamplerCustomAdvanced": 2, "ResizeImageMaskNode": 1,
    "GetImageSize": 3, "CreateVideo": 1, "PrimitiveInt": 1,
    "PrimitiveBoolean": 1, "PrimitiveStringMultiline": 1,
    "ComfyMathExpression": 3, "ComfySwitchNode": 1,
    "TextGenerateLTX2Prompt": 1, "PreviewAny": 1,
}

# UI widgets_values sıralaması → API girdi adları. None = UI-only widget
# (control_after_generate / upload düğmesi gibi), API'ye verilmez. Sıralar
# ComfyUI a7b1d39d şemalarındaki girdi sırasına birebir göredir.
_WIDGET_ORDER: dict[str, tuple[str | None, ...]] = {
    "LoadImage": ("image", None),
    "SaveVideo": ("filename_prefix", "format", None),
    "UNETLoader": ("unet_name", "weight_dtype"),
    "VAELoader": ("vae_name",),
    "CLIPLoader": ("clip_name", "type", "device"),
    "CLIPTextEncode": ("text",),
    "VAEDecodeTiled": ("tile_size", "overlap", "temporal_size", "temporal_overlap"),
    "EmptyLTXVLatentVideo": ("width", "height", "length", "batch_size"),
    "LTXVAddGuide": ("frame_idx", "strength"),
    "LTXVConditioning": ("frame_rate",),
    "LTXVPreprocess": ("img_compression",),
    "LTXVEmptyLatentAudio": ("frames_number", "frame_rate", "batch_size"),
    "LTXVDualCFGGuider": ("video_cfg", "audio_cfg"),
    "RandomNoise": ("noise_seed", None),
    "SamplerEulerAncestral": ("eta", "s_noise"),
    "ManualSigmas": ("sigmas",),
    "ResizeImageMaskNode": (
        "resize_type", "resize_type.width", "resize_type.height",
        "resize_type.crop", "scale_method",
    ),
    "GetImageSize": (),
    "CreateVideo": ("fps", "bit_depth"),
    "PrimitiveInt": ("value", None),
    "PrimitiveBoolean": ("value",),
    "PrimitiveStringMultiline": ("value",),
    "ComfyMathExpression": ("expression",),
    "ComfySwitchNode": ("switch",),
    "TextGenerateLTX2Prompt": (
        "prompt", "max_length", "sampling_mode", "temperature", "top_k",
        "top_p", "min_p", "repetition_penalty", "seed", "presence_penalty",
        "thinking", "use_default_template",
    ),
    "PreviewAny": (),
    "LTXVConcatAVLatent": (),
    "LTXVSeparateAVLatent": (),
    "LTXVAudioVAEDecode": (),
    "LTXVCropGuides": (),
    "SamplerCustomAdvanced": (),
}

_SKIP_TYPES = frozenset({"MarkdownNote"})

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_CANDIDATES = (
    _REPO_ROOT / "scripts" / "ltx25" / "templates" / "ltx25_flf2v_template.json",
    _REPO_ROOT / ".tmp" / "ltx25_flf2v_template.json",
)


def load_template(path: str | Path | None = None) -> dict:
    """UI-format FLF2V şablonunu yükler (varsayılan: repo içindeki pinli kopya)."""
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    for candidate in _TEMPLATE_CANDIDATES:
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        "ltx25_flf2v_template.json bulunamadı; path= ile açıkça verin "
        f"(aranan: {', '.join(str(c) for c in _TEMPLATE_CANDIDATES)})"
    )


class _GraphBuilder:
    """Tek seviyelik subgraph açma (frontend'in yaptığı dönüşümün 1:1'i)."""

    def __init__(self, ui: dict):
        self.ui = ui
        self.subgraphs = {
            s["id"]: s for s in ui.get("definitions", {}).get("subgraphs", [])
        }
        self.top_links = {l[0]: l for l in ui.get("links", []) or []}
        self.api: dict[str, dict] = {}
        # partner ui id → subgraph tanımı (expand_ui_workflow doldurur)
        self._prefix_to_sub: dict[str, dict] = {}
        # (api_id, input_key) → çözülmemiş ui link ref'i (top-level kapsamı)
        self._pending_top: list[tuple[str, str, int | tuple]] = []
        # partner çıktı slotları: partner_ui_id → {slot_k: (api_id, out_slot)}
        self._partner_outputs: dict[str, dict[int, tuple[str, int]]] = {}

    # ---- yardımcılar -------------------------------------------------
    def _class_of(self, node: dict) -> str:
        return node["type"]

    def _widgets(self, node: dict) -> dict[str, Any]:
        table = _WIDGET_ORDER.get(self._class_of(node))
        values = node.get("widgets_values") or []
        if table is None:
            # Bilinmeyen sınıf: widget olarak işaretlenmiş girdileri sırayla eşle.
            names = [
                i.get("widget", {}).get("name") or i["name"]
                for i in node.get("inputs", [])
                if "widget" in i
            ]
            table = tuple(names)
        out: dict[str, Any] = {}
        for name, value in zip(table, values):
            if name is not None:
                out[name] = value
        return out

    def _api_node(self, api_id: str, ui_node: dict, title: str | None = None) -> dict:
        cls = self._class_of(ui_node)
        entry = {
            "class_type": cls,
            "inputs": self._widgets(ui_node),
        }
        if title or ui_node.get("title"):
            entry["_meta"] = {"title": title or ui_node["title"]}
        self.api[api_id] = entry
        # Bağlantı girdileri kaydedilir; widget'e bağlı linkler pozisyonel değeri ezer.
        for inp in ui_node.get("inputs", []):
            key = (inp.get("widget", {}) or {}).get("name") or inp["name"]
            link = inp.get("link")
            if link is not None:
                self._pending_top.append((api_id, key, link))
            # null link + widget girdisi: pozisyonel değer zaten _widgets'ta.
        return entry

    def _resolve_top_link(self, link_id: int) -> tuple[str, int]:
        link = self.top_links[link_id]
        origin, origin_slot = str(link[1]), link[2]
        if origin in self._partner_outputs:
            origin, origin_slot = self._partner_outputs[origin][origin_slot]
        return origin, origin_slot

    # ---- partner (subgraph) açma ------------------------------------
    def _expand_partner(self, node: dict) -> None:
        sub = self.subgraphs.get(node["type"])
        if sub is None:
            raise ValueError(
                f"Subgraph tanımı bulunamadı: {node['type']!r} (id={node.get('id')})"
            )
        prefix = f"{node['id']}"
        sub_links = {l["id"]: l for l in sub.get("links", [])}
        sub_nodes = {n["id"]: n for n in sub.get("nodes", [])}

        # 1) Subgraph giriş slotları → değerler.
        #    Slot sırası = sub['inputs'] sırası. Dış düğümün 'inputs'
        #    girdileri isimle slot'a eşlenir; link'i olan slot dış bağlantı
        #    alır, diğerleri partner widgets_values'ını sırayla tüketir.
        name2slot = {si["name"]: i for i, si in enumerate(sub.get("inputs", []))}
        linked_slots: dict[int, int] = {}       # slot → dış ui link id
        for inp in node.get("inputs", []):
            slot = name2slot.get(inp["name"])
            if slot is None:
                continue
            if inp.get("link") is not None:
                linked_slots[slot] = inp["link"]
        widget_slots = [
            i for i in range(len(sub.get("inputs", []))) if i not in linked_slots
        ]
        widget_values = node.get("widgets_values") or []
        slot_values: dict[int, tuple[str, Any]] = {}
        for order, slot in enumerate(widget_slots):
            if order < len(widget_values):
                slot_values[slot] = ("value", widget_values[order])
        for slot, link_id in linked_slots.items():
            slot_values[slot] = ("link", link_id)

        # 2) İç düğümleri API düğümü olarak yarat.
        for inner in sub.get("nodes", []):
            if inner["type"] in _SKIP_TYPES:
                continue
            api_id = f"{prefix}_{inner['id']}"
            entry = {
                "class_type": inner["type"],
                "inputs": self._widgets(inner),
            }
            if inner.get("title"):
                entry["_meta"] = {"title": inner["title"]}
            self.api[api_id] = entry

            for inp in inner.get("inputs", []):
                key = (inp.get("widget", {}) or {}).get("name") or inp["name"]
                link_id = inp.get("link")
                if link_id is None:
                    continue  # null link: pozisyonel widget değeri zaten var
                link = sub_links[link_id]
                origin_id = link["origin_id"]
                if origin_id == -10:  # subgraph giriş slotu
                    slot = link["origin_slot"]
                    if slot not in slot_values:
                        raise ValueError(
                            f"Subgraph slot {slot} için değer yok (partner {node['id']})"
                        )
                    kind, value = slot_values[slot]
                    if kind == "value":
                        entry["inputs"][key] = value
                    else:
                        src, out_slot = self._resolve_top_link(value)
                        entry["inputs"][key] = [src, out_slot]
                else:
                    self._pending_top.append(
                        (api_id, key, ("sub", prefix, link_id))
                    )

        # 3) Subgraph çıkış slotları → partner çıktı eşlemesi.
        out_map: dict[int, tuple[str, int]] = {}
        for k, out in enumerate(sub.get("outputs", [])):
            lids = out.get("linkIds") or []
            if not lids:
                continue
            link = sub_links[lids[0]]
            out_map[k] = (f"{prefix}_{link['origin_id']}", link["origin_slot"])
        self._partner_outputs[str(node["id"])] = out_map

    # ---- ana akış ----------------------------------------------------
    @staticmethod
    def _is_uuid_type(node_type: str) -> bool:
        """class_type 36 karakterli UUID'ye benziyor mu (frontend partner düğümü)?"""
        return (
            isinstance(node_type, str)
            and len(node_type) == 36
            and node_type.count("-") == 4
            and all(c in "0123456789abcdefABCDEF-" for c in node_type)
        )

    def build(self) -> dict[str, dict]:
        partner_ids = set(self.subgraphs)
        for node in self.ui.get("nodes", []):
            if node["type"] in _SKIP_TYPES:
                continue
            if node["type"] in partner_ids:
                self._expand_partner(node)
            elif self._is_uuid_type(node["type"]):
                raise ValueError(
                    f"Subgraph tanımı bulunamadı: {node['type']!r} (id={node.get('id')})"
                )
            else:
                self._api_node(str(node["id"]), node)

        # Bağlantıları çöz.
        for api_id, key, ref in self._pending_top:
            if isinstance(ref, tuple):  # subgraph içi bağlantı: ("sub", prefix, link_id)
                _, prefix, link_id = ref
                sub = self._prefix_to_sub[prefix]
                link = {l["id"]: l for l in sub.get("links", [])}[link_id]
                src_id = f"{prefix}_{link['origin_id']}"
                self.api[api_id]["inputs"][key] = [src_id, link["origin_slot"]]
            else:
                src, out_slot = self._resolve_top_link(ref)
                self.api[api_id]["inputs"][key] = [src, out_slot]
        return self.api


def expand_ui_workflow(ui: dict) -> dict[str, dict]:
    """UI-format workflow JSON'unu /prompt API-format graph'ına çevirir.

    - ``definitions.subgraphs`` içindeki partner düğümler (UUID class_type)
      gerçek düğümlere açılır; sonuç graph'ında UUID class_type kalmaz.
    - Dönen değer: ``{node_id: {"class_type": ..., "inputs": {...}}}``.
    """
    builder = _GraphBuilder(copy.deepcopy(ui))
    # partner id → subgraph eşlemesini önceden kur (bağlantı çözümü için)
    for node in ui.get("nodes", []):
        if node["type"] in builder.subgraphs:
            builder._prefix_to_sub[str(node["id"])] = builder.subgraphs[node["type"]]
    return builder.build()


# ---------------------------------------------------------------------------
# FLF2V'ye özgü kolaylaştırıcı katman
# ---------------------------------------------------------------------------

# Subgraph giriş slotlarının etiketleri (şablondaki label / name).
_SLOT_LABELS = {
    "first_frame": "first_frame",
    "last_frame": "last_frame",
    "prompt": "prompt",
    "prompt_enhance": "prompt_enhance",
    "duration": "duration",
    "width": "width",
    "height": "height",
    "noise_seed": "noise_seed",
    "fram_rate": "fram_rate",  # şablondaki (yanlış yazılmış) etiket aynen korunur
    "unet_name": "unet_name",
    "video_vae": "video_vae",
    "audio_vae": "audio_vae",
    "clip_name": "clip_name",
    "prompt_enhance_model": "prompt_enhance_model",
}

_ENHANCER_CLASSES = (
    "TextGenerateLTX2Prompt", "ComfySwitchNode", "PrimitiveBoolean",
    "PreviewAny", "CLIPLoader",
)


def _find_partner(ui: dict) -> dict:
    for node in ui.get("nodes", []):
        if node["type"] in {s["id"] for s in ui.get("definitions", {}).get("subgraphs", [])}:
            return node
    raise ValueError("Şablonda subgraph partner düğümü bulunamadı")


def _subgraph_of(ui: dict, partner: dict) -> dict:
    for s in ui["definitions"]["subgraphs"]:
        if s["id"] == partner["type"]:
            return s
    raise ValueError("Partner için subgraph tanımı yok")


def _set_slot_widget(partner: dict, sub: dict, label: str, value: Any) -> None:
    """Partnerin widget-backed slot değerini etikete göre günceller."""
    name2slot = {si["name"]: i for i, si in enumerate(sub.get("inputs", []))}
    slot_by_label = {}
    for i, si in enumerate(sub.get("inputs", [])):
        key = si.get("label") or si["name"]
        slot_by_label[key] = i
    slot = slot_by_label.get(label, name2slot.get(label))
    if slot is None:
        raise KeyError(f"Subgraph slotu bulunamadı: {label!r}")
    # Widget slotları = link'siz slotlar; sırayla widgets_values tüketilir.
    linked = {
        name2slot[inp["name"]]: inp["link"]
        for inp in partner.get("inputs", [])
        if inp.get("link") is not None and inp["name"] in name2slot
    }
    widget_slots = [i for i in range(len(sub["inputs"])) if i not in linked]
    order = widget_slots.index(slot)
    while len(partner.setdefault("widgets_values", [])) <= order:
        partner["widgets_values"].append(None)
    partner["widgets_values"][order] = value


def _set_image_source(ui: dict, partner: dict, sub: dict, label: str, filename: str) -> None:
    """first/last frame slotunu besleyen LoadImage düğümünün dosyasını değiştirir."""
    name2slot = {si["name"]: i for i, si in enumerate(sub.get("inputs", []))}
    slot_by_label = {}
    for i, si in enumerate(sub.get("inputs", [])):
        slot_by_label[si.get("label") or si["name"]] = i
    slot = slot_by_label.get(label)
    if slot is None:
        raise KeyError(f"Subgraph slotu bulunamadı: {label!r}")
    entry = next(
        (inp for inp in partner.get("inputs", []) if name2slot.get(inp["name"]) == slot),
        None,
    )
    link_id = entry and entry.get("link")
    if link_id is None:
        raise ValueError(f"{label!r} slotu bir LoadImage bağlantısına bağlı değil")
    link = next(l for l in ui["links"] if l[0] == link_id)
    src = next(n for n in ui["nodes"] if n["id"] == link[1])
    if src["type"] != "LoadImage":
        raise ValueError(f"{label!r} kaynağı LoadImage değil: {src['type']}")
    src["widgets_values"][0] = filename


def _prune_enhance_branch(graph: dict[str, dict]) -> dict[str, dict]:
    """prompt_enhance=False için enhancer dalını söker ve prompt'u doğrudan bağlar.

    Şablondaki akış: PrimitiveStringMultiline(prompt) → [TextGenerateLTX2Prompt
    (enhance) ve ComfySwitchNode.on_false]; switch çıktısı pozitif
    CLIPTextEncode.text'e gider. Enhance kapalıyken switch gereksizdir; ayrıca
    enhancer CLIPLoader'ı (opsiyonel gemma4_e2b_it modeli) sunucuda tutmak,
    dosya yoksa /prompt doğrulamasını (value_not_in_list) boşa düşürür.
    """
    switches = [nid for nid, n in graph.items() if n["class_type"] == "ComfySwitchNode"]
    if not switches:
        return graph
    removed: set[str] = set()
    for sid in switches:
        inputs = graph[sid]["inputs"]
        raw_source = inputs.get("on_false")
        for nid, node in graph.items():
            if node["class_type"] == "CLIPTextEncode" and node["inputs"].get("text") == [sid, 0]:
                if raw_source is not None:
                    node["inputs"]["text"] = list(raw_source)
        # Enhancer zincirini kaldır: switch + on_true kaynağı + onun CLIP'i.
        removed.add(sid)
        switch_ref = inputs.get("switch")
        if switch_ref:
            feeder = graph.get(str(switch_ref[0]))
            if feeder and feeder["class_type"] == "PrimitiveBoolean":
                removed.add(str(switch_ref[0]))
        on_true = inputs.get("on_true")
        if on_true:
            gen_id = str(on_true[0])
            removed.add(gen_id)
            clip_ref = graph.get(gen_id, {}).get("inputs", {}).get("clip")
            if clip_ref:
                removed.add(str(clip_ref[0]))
    for nid in removed:
        graph.pop(nid, None)
    # Yetim kalan yardımcı düğümleri (ör. switch'i besleyen PreviewAny) düşür:
    # yalnızca hiçbir yerden tüketilmeyen "görüntüleme" düğümleri kaldırılır;
    # iş düğümleri (loader/sampler/decode) asla dokunulmaz.
    while True:
        consumed: set[str] = set()
        for node in graph.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    consumed.add(value[0])
        orphan_helpers = {
            nid
            for nid, node in graph.items()
            if nid not in consumed
            and node["class_type"] in ("PreviewAny",)
        }
        if not orphan_helpers:
            break
        for nid in orphan_helpers:
            graph.pop(nid, None)
    return graph


def build_flf2v_graph(
    *,
    prompt: str,
    first_image: str,
    last_image: str,
    width: int = 1280,
    height: int = 720,
    fps: int = 24,
    duration_sec: int = 5,
    seed: int | None = None,
    prompt_enhance: bool = False,
    negative_prompt: str | None = None,
    transformer: str | None = None,
    video_vae: str | None = None,
    audio_vae: str | None = None,
    text_encoder: str | None = None,
    enhancer_model: str | None = None,
    filename_prefix: str = "video/ltx25_flf2v",
    template: dict | None = None,
    template_path: str | Path | None = None,
) -> dict[str, dict]:
    """Resmî LTX-2.5 FLF2V (First & Last Frame) workflow'unu /prompt graph'ına çevirir.

    Parametreler şablonun subgraph slotlarına uygulanır; dönen sözlük doğrudan
    ``POST /prompt`` gövdesindeki ``prompt`` alanına girer. Varsayılan model
    dosya adları şablondan gelir; ``transformer`` / ``video_vae`` / ``audio_vae``
    / ``text_encoder`` / ``enhancer_model`` ile ezebilirsiniz.
    """
    ui = copy.deepcopy(template) if template is not None else load_template(template_path)
    partner = _find_partner(ui)
    sub = _subgraph_of(ui, partner)

    if seed is None:
        seed = random.randrange(2**63)
    _set_image_source(ui, partner, sub, "first_frame", first_image)
    _set_image_source(ui, partner, sub, "last_frame", last_image)
    _set_slot_widget(partner, sub, "prompt", prompt)
    _set_slot_widget(partner, sub, "prompt_enhance", bool(prompt_enhance))
    _set_slot_widget(partner, sub, "duration", int(duration_sec))
    _set_slot_widget(partner, sub, "width", int(width))
    _set_slot_widget(partner, sub, "height", int(height))
    _set_slot_widget(partner, sub, "noise_seed", int(seed))
    _set_slot_widget(partner, sub, "fram_rate", int(fps))
    if transformer is not None:
        _set_slot_widget(partner, sub, "unet_name", transformer)
    if video_vae is not None:
        _set_slot_widget(partner, sub, "video_vae", video_vae)
    if audio_vae is not None:
        _set_slot_widget(partner, sub, "audio_vae", audio_vae)
    if text_encoder is not None:
        _set_slot_widget(partner, sub, "clip_name", text_encoder)
    if enhancer_model is not None:
        _set_slot_widget(partner, sub, "prompt_enhance_model", enhancer_model)

    graph = expand_ui_workflow(ui)

    # SaveVideo çıktı öneki (dış düğüm).
    for node in graph.values():
        if node["class_type"] == "SaveVideo":
            node["inputs"]["filename_prefix"] = filename_prefix

    # Negatif prompt: LTXVConditioning.negative besleyen CLIPTextEncode.
    if negative_prompt is not None:
        conditioning = next(
            n for n in graph.values() if n["class_type"] == "LTXVConditioning"
        )
        neg_ref = conditioning["inputs"]["negative"]
        graph[str(neg_ref[0])]["inputs"]["text"] = negative_prompt

    if not prompt_enhance:
        graph = _prune_enhance_branch(graph)
    return graph


def build_api_payload(
    graph: dict[str, dict],
    *,
    client_id: str | None = None,
    prompt_id: str | None = None,
    extra_data: dict | None = None,
) -> dict:
    """Graph'ı POST /prompt gövdesine sarar (``{"prompt": graph, ...}``)."""
    payload: dict[str, Any] = {"prompt": graph}
    if client_id is not None:
        payload["client_id"] = client_id
    if prompt_id is not None:
        payload["prompt_id"] = prompt_id
    if extra_data is not None:
        payload["extra_data"] = extra_data
    return payload


if __name__ == "__main__":  # hızlı bakış: python scripts/ltx25/ltx25_api_graph.py
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prompt", default="A slow cinematic test shot.")
    parser.add_argument("--first", default="robot_hand.png")
    parser.add_argument("--last", default="robot_hand_energy.png")
    parser.add_argument("--template", default=None)
    parser.add_argument("--out", default="-")
    args = parser.parse_args()

    graph = build_flf2v_graph(
        prompt=args.prompt, first_image=args.first, last_image=args.last,
        template_path=args.template,
    )
    text = json.dumps(build_api_payload(graph), indent=2, ensure_ascii=False)
    if args.out == "-":
        sys.stdout.write(text + "\n")
    else:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"yazıldı: {args.out} ({len(graph)} düğüm)")
