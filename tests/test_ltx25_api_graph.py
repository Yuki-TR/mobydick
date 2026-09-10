"""scripts/ltx25/ltx25_api_graph.py birim testleri (GPU'suz, saf Python).

Doğrulamalar Comfy-Org/ComfyUI @ a7b1d39d342d102f305797fb5ba12dc304d9c1f5
kaynak şemalarına karşı pinlidir (bkz. modül docstring'i):
- /prompt'un partner (subgraph, UUID class_type) düğümlerini reddettiği
  (execution.py::validate_prompt → missing_node_type),
- v3 (io.Schema) düğümlerinin DynamicCombo/Autogrow girdilerinin API
  anahtarlarıyla (nokta-path) serileştirildiği (comfy_api/latest/_io.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(REPO_ROOT := Path(__file__).resolve().parents[1] / "scripts" / "ltx25"))
import ltx25_api_graph as m  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "scripts" / "ltx25" / "templates" / "ltx25_flf2v_template.json"


def _base_graph(**kwargs) -> dict:
    defaults = dict(
        prompt="A cinematic test shot.",
        first_image="first.png",
        last_image="last.png",
        seed=42,
        prompt_enhance=False,
    )
    defaults.update(kwargs)
    return m.build_flf2v_graph(**defaults)


# ---------------------------------------------------------------------------
# partner node / subgraph çözümlemesi
# ---------------------------------------------------------------------------

def test_template_partner_node_is_subgraph_uuid() -> None:
    """Şablondaki partner düğüm class_type'ı bir subgraph UUID'sidir (frontend-only)."""
    ui = m.load_template(TEMPLATE)
    partner = m._find_partner(ui)
    sub = m._subgraph_of(ui, partner)
    assert partner["type"] == m.LTX25_FLF2V_SUBGRAPH_ID
    assert partner["type"] == sub["id"]
    # UUID formatı: /prompt bunu NODE_CLASS_MAPPINGS'te bulamaz.
    assert partner["type"].count("-") == 4 and len(partner["type"]) == 36


def test_expansion_has_no_uuid_class_types() -> None:
    graph = _base_graph(prompt_enhance=True)
    assert graph
    for node_id, node in graph.items():
        assert node["class_type"] not in ("", None)
        assert node["class_type"] != m.LTX25_FLF2V_SUBGRAPH_ID
        assert node["class_type"] in m.API_NODE_CLASSES, node_id


def test_expansion_preserves_all_inner_nodes_and_links() -> None:
    """Subgraph'taki her iç düğüm ve bağlantı, açılan graph'ta birebir korunmalı."""
    ui = m.load_template(TEMPLATE)
    partner = m._find_partner(ui)
    sub = m._subgraph_of(ui, partner)
    graph = _base_graph(prompt_enhance=True, template=ui)

    inner_ids = [n["id"] for n in sub["nodes"] if n["type"] != "MarkdownNote"]
    for inner_id in inner_ids:
        node = f"251_{inner_id}"
        assert node in graph, f"iç düğüm eksik: {node}"
    for link in sub["links"]:
        target = f"251_{link['target_id']}"
        source = f"251_{link['origin_id']}"
        if target not in graph or source not in graph:
            continue  # subgraph giriş/çıkış sanal düğümleri
        node = next(n for n in sub["nodes"] if n["id"] == link["target_id"])
        inputs = node.get("inputs") or []
        if link["target_slot"] >= len(inputs):
            continue
        key = (inputs[link["target_slot"]].get("widget") or {}).get("name") or inputs[link["target_slot"]]["name"]
        value = graph[target]["inputs"].get(key)
        # Subgraph giriş slotu (-10) literal değere çözülür; bu test yalnızca
        # iç-düğüm→iç-düğüm bağlantılarını doğrular.
        if link["origin_id"] == -10:
            continue
        assert value == [source, link["origin_slot"]], (target, key, value)


def test_outer_links_routed_through_partner() -> None:
    graph = _base_graph()
    # LoadImage'lar partnerin first/last slotlarını besler.
    assert graph["31"]["class_type"] == "LoadImage"
    assert graph["39"]["class_type"] == "LoadImage"
    assert graph["251_213"]["inputs"]["input"] == ["31", 0]
    assert graph["251_214"]["inputs"]["input"] == ["39", 0]
    # Partnerin VIDEO çıktısı SaveVideo'ya akar.
    assert graph["68"]["inputs"]["video"] == ["251_218", 0]


# ---------------------------------------------------------------------------
# /prompt sözleşmesi: JSON-serializable, tek output düğümü, çevrim bağımsız
# ---------------------------------------------------------------------------

def test_graph_is_json_serializable_and_payload_shape() -> None:
    graph = _base_graph(prompt_enhance=True)
    payload = m.build_api_payload(graph, client_id="cid", prompt_id=None, extra_data={"x": 1})
    text = json.dumps(payload)  # TypeError yükseltmemeli
    loaded = json.loads(text)
    assert loaded["prompt"] == graph
    assert loaded["client_id"] == "cid"
    assert loaded["extra_data"] == {"x": 1}
    assert "prompt_id" not in loaded  # None serileştirilmedi


def test_output_nodes_present() -> None:
    """Sunucu çıktı düğümsüz prompt'u reddeder (prompt_no_outputs)."""
    graph = _base_graph()
    output_nodes = {n["class_type"] for n in graph.values() if n["class_type"] in m._OUTPUT_NODES}
    assert "SaveVideo" in output_nodes
    assert graph["68"]["inputs"]["filename_prefix"] == "video/ltx25_flf2v"


def test_graph_is_acyclic_and_links_resolve() -> None:
    graph = _base_graph(prompt_enhance=True)
    state: dict[str, int] = {}  # 0=zorlanıyor, 1=çözüldü

    def visit(node_id: str, stack: tuple[str, ...]) -> None:
        if state.get(node_id) == 1:
            return
        assert node_id not in stack, f"çevrim: {' -> '.join(stack + (node_id,))}"
        node = graph[node_id]
        for key, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in graph, f"{node_id}.{key} → bilinmeyen {value[0]}"
                assert 0 <= value[1] < m._OUTPUT_COUNT[graph[value[0]]["class_type"]]
                visit(value[0], stack + (node_id,))

        state[node_id] = 1

    for node_id in graph:
        visit(node_id, ())
    assert len(state) == len(graph)


# ---------------------------------------------------------------------------
# parametre iletimi (subgraph slot eşlemesi)
# ---------------------------------------------------------------------------

def test_parameter_slots_propagate() -> None:
    graph = _base_graph(
        prompt="PROMPT_TEXT", duration_sec=4, width=992, height=544, fps=25,
        seed=777, transformer="t.safetensors", video_vae="vv.safetensors",
        audio_vae="av.safetensors", text_encoder="te.safetensors",
    )
    assert graph["251_252"]["inputs"]["value"] == "PROMPT_TEXT"
    assert graph["251_196"]["inputs"]["noise_seed"] == 777
    assert graph["251_198"]["inputs"]["value"] == 4          # duration
    assert graph["251_215"]["inputs"]["value"] == 992        # width
    assert graph["251_216"]["inputs"]["value"] == 544        # height
    assert graph["251_205"]["inputs"]["value"] == 25         # fps
    assert graph["251_230"]["inputs"]["unet_name"] == "t.safetensors"
    assert graph["251_229"]["inputs"]["vae_name"] == "vv.safetensors"
    assert graph["251_227"]["inputs"]["vae_name"] == "av.safetensors"
    assert graph["251_228"]["inputs"]["clip_name"] == "te.safetensors"


def test_default_model_files_from_template() -> None:
    graph = _base_graph()
    assert graph["251_230"]["inputs"]["unet_name"] == (
        "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
    )
    assert graph["251_229"]["inputs"]["vae_name"] == "ltx-2.5-video-vae-bf16.safetensors"
    assert graph["251_227"]["inputs"]["vae_name"] == "ltx-2.5-audio-vae-bf16.safetensors"
    assert graph["251_228"]["inputs"]["clip_name"] == (
        "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
    )
    assert graph["251_228"]["inputs"]["type"] == "ltxv"


def test_first_last_frame_guide_wiring() -> None:
    """FLF2V çekirdeği: ilk kare idx=0, son kare idx=-1, strength 0.7."""
    graph = _base_graph()
    first_guide, last_guide = graph["251_206"], graph["251_204"]
    assert first_guide["inputs"]["frame_idx"] == 0
    assert last_guide["inputs"]["frame_idx"] == -1
    assert first_guide["inputs"]["strength"] == 0.7 == last_guide["inputs"]["strength"]
    # 199 ilk kareyi (213→199), 195 son kareyi (214→195) işler.
    assert first_guide["inputs"]["image"] == ["251_199", 0]
    assert last_guide["inputs"]["image"] == ["251_195", 0]
    assert first_guide["inputs"]["latent"] == ["251_201", 0]  # EmptyLTXVLatentVideo
    # Zincir: ilk guide → son guide → CropGuides → VAEDecodeTiled.
    assert last_guide["inputs"]["positive"] == ["251_206", 0]
    assert last_guide["inputs"]["latent"] == ["251_206", 2]
    assert graph["251_219"]["inputs"]["samples"] == ["251_200", 2]


def test_duration_frames_expression() -> None:
    """LTX-2.5 çerçeve sayısı: duration*fps + 1 (şablondaki 'a * b + 1' ifadesi)."""
    graph = _base_graph(duration_sec=4, fps=25)
    math_node = graph["251_226"]
    assert math_node["class_type"] == "ComfyMathExpression"
    assert math_node["inputs"]["expression"] == "a * b + 1"
    assert math_node["inputs"]["values.a"] == ["251_198", 0]  # duration
    assert math_node["inputs"]["values.b"] == ["251_205", 0]  # fps
    frames_ref = ["251_226", 1]  # INT çıkışı
    assert graph["251_201"]["inputs"]["length"] == frames_ref
    assert graph["251_197"]["inputs"]["frames_number"] == frames_ref


def test_sampler_constants_match_template() -> None:
    graph = _base_graph()
    assert graph["251_208"]["inputs"] == {"eta": 0, "s_noise": 1}
    assert graph["251_235"]["inputs"]["video_cfg"] == 1
    assert graph["251_235"]["inputs"]["audio_cfg"] == 1
    assert graph["251_239"]["inputs"]["sigmas"] == (
        "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
    )
    assert graph["251_219"]["inputs"]["temporal_overlap"] == 16
    assert graph["251_218"]["inputs"]["bit_depth"] == 8
    assert graph["251_195"]["inputs"]["img_compression"] == 18


def test_negative_prompt_override() -> None:
    graph = _base_graph(negative_prompt="custom negative")
    assert graph["251_217"]["inputs"]["text"] == "custom negative"
    cond = graph["251_202"]
    assert cond["inputs"]["negative"] == ["251_217", 0]
    # Varsayılan: şablonun uzun negatif prompt'u.
    default_graph = _base_graph()
    assert len(default_graph["251_217"]["inputs"]["text"]) > 500


def test_resize_nodes_track_width_height() -> None:
    graph = _base_graph(width=1280, height=720)
    for node_id in ("251_213", "251_214"):
        inputs = graph[node_id]["inputs"]
        assert inputs["resize_type"] == "scale dimensions"           # DynamicCombo seçimi
        assert inputs["resize_type.width"] == ["251_215", 0]
        assert inputs["resize_type.height"] == ["251_216", 0]
        assert inputs["resize_type.crop"] == "center"
        assert inputs["scale_method"] == "nearest-exact"


def test_resize_dimensions_follow_custom_size() -> None:
    graph = _base_graph(width=640, height=384)
    # Resize width/height hâlâ PrimitiveInt linkleri; PrimitiveInt değerleri değişti.
    assert graph["251_215"]["inputs"]["value"] == 640
    assert graph["251_216"]["inputs"]["value"] == 384


# ---------------------------------------------------------------------------
# prompt_enhance dalı
# ---------------------------------------------------------------------------

def test_enhance_branch_included_when_enabled() -> None:
    graph = _base_graph(prompt_enhance=True)
    classes = {n["class_type"] for n in graph.values()}
    assert "ComfySwitchNode" in classes
    assert "TextGenerateLTX2Prompt" in classes
    switch = next(n for n in graph.values() if n["class_type"] == "ComfySwitchNode")
    assert switch["inputs"]["switch"] == ["251_250", 0]   # PrimitiveBoolean(prompt_enhance)
    assert switch["inputs"]["on_false"] == ["251_252", 0]  # ham prompt
    assert switch["inputs"]["on_true"] == ["251_247", 0]   # TextGenerateLTX2Prompt
    # Pozitif CLIPTextEncode switch'ten beslenir.
    assert graph["251_222"]["inputs"]["text"] == ["251_248", 0]
    # Enhancer şablon parametreleri korunur.
    gen = graph["251_247"]["inputs"]
    assert gen["max_length"] == 600
    assert gen["sampling_mode"] == "on"  # DynamicCombo seçimi
    assert gen["temperature"] == 0.7
    assert gen["top_k"] == 64
    assert gen["top_p"] == 0.95
    assert gen["min_p"] == 0.05
    assert gen["repetition_penalty"] == 1.15


def test_enhance_branch_pruned_when_disabled() -> None:
    graph = _base_graph(prompt_enhance=False)
    classes = {n["class_type"] for n in graph.values()}
    assert "ComfySwitchNode" not in classes
    assert "TextGenerateLTX2Prompt" not in classes
    # Enhancer CLIP'i (opsiyonel model) yükleyen düğüm de kalkmalı; aksi hâlde
    # dosya yoksa /prompt value_not_in_list ile reddeder.
    clip_files = [n["inputs"]["clip_name"] for n in graph.values() if n["class_type"] == "CLIPLoader"]
    assert clip_files == ["gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"]
    # Pozitif prompt artık doğrudan ham promptPrimitiveStringMultiline'dan gelir.
    assert graph["251_222"]["inputs"]["text"] == ["251_252", 0]
    assert graph["251_252"]["inputs"]["value"] == "A cinematic test shot."


def test_prune_keeps_graph_valid() -> None:
    graph = _base_graph(prompt_enhance=False)
    for node_id, node in graph.items():
        assert node["class_type"] in m.API_NODE_CLASSES, node_id
        for key, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in graph, f"{node_id}.{key} kopuk"


# ---------------------------------------------------------------------------
# expand_ui_workflow genel davranışı
# ---------------------------------------------------------------------------

def test_expand_is_deterministic_and_pure() -> None:
    ui1 = m.load_template(TEMPLATE)
    ui2 = m.load_template(TEMPLATE)
    g1 = m.expand_ui_workflow(ui1)
    g2 = m.expand_ui_workflow(ui2)
    assert g1 == g2
    # Girdi JSON mutasyona uğramamalı.
    original = m.load_template(TEMPLATE)
    assert list(original["nodes"][0]["widgets_values"]) == list(
        m.load_template(TEMPLATE)["nodes"][0]["widgets_values"]
    )


def test_expand_unknown_subgraph_raises() -> None:
    ui = {
        "nodes": [{"id": 1, "type": "00000000-0000-0000-0000-000000000000"}],
        "links": [],
    }
    with pytest.raises(ValueError, match="Subgraph tanımı bulunamadı"):
        m.expand_ui_workflow(ui)


def test_seed_defaults_differ_and_respect_explicit() -> None:
    g1 = m.build_flf2v_graph(
        prompt="x", first_image="a.png", last_image="b.png", prompt_enhance=False
    )
    g2 = m.build_flf2v_graph(
        prompt="x", first_image="a.png", last_image="b.png", prompt_enhance=False
    )
    s1 = g1["251_196"]["inputs"]["noise_seed"]
    s2 = g2["251_196"]["inputs"]["noise_seed"]
    assert isinstance(s1, int) and 0 <= s1 < 2**63
    assert s1 != s2
    g3 = _base_graph(seed=5)
    assert g3["251_196"]["inputs"]["noise_seed"] == 5


def test_template_path_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "tpl.json"
    target.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    graph = m.build_flf2v_graph(
        prompt="x", first_image="a.png", last_image="b.png", template_path=target
    )
    assert "68" in graph and graph["68"]["class_type"] == "SaveVideo"
