"""
Academic metrics ported from SciTikZ (2026).

Code metrics: Token Edit Distance (TED) + CrystalBLEU via Pygments TeXLexer
Image metrics: SSIM + LPIPS with white-border trimming

All logic preserved byte-for-byte from the official Benchmark_Eval/eval/ source.
Gracefully degrades when optional dependencies are missing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from collections import Counter
from functools import cached_property
from hashlib import md5
from itertools import chain, tee
from pathlib import Path
from pickle import dump, load
import math
import os
import re

import torch
import torchvision.transforms as T
from PIL import Image, ImageChops

# ===================== optional deps =====================
try:
    from crystalbleu import corpus_bleu
except Exception:
    corpus_bleu = None

try:
    from pygments.lexers.markup import TexLexer
    from pygments.token import Comment, Name, Text
except Exception:
    TexLexer = None; Comment = None; Name = None; Text = None

try:
    from sacremoses import MosesTokenizer
except Exception:
    MosesTokenizer = None

try:
    from torchmetrics.text import ExtendedEditDistance
    from torchmetrics.functional.text.eed import (
        _compute_sentence_statistics, _preprocess_en, _preprocess_ja,
    )
    from torchmetrics.functional.text.helper import _validate_inputs
except Exception:
    ExtendedEditDistance = None

try:
    from pytorch_msssim import ssim as ssim_fn
except Exception:
    ssim_fn = None

try:
    import lpips as _lpips_lib
except Exception:
    _lpips_lib = None

# ===================== result dataclasses =====================

@dataclass
class CodeMetricResult:
    ted_dist: float = float("nan")
    ted_dist_norm: float = float("nan")
    ted_sim: float = 0.0
    crystalbleu: float = 0.0
    crystalbleu_mode: str = "sentence"


@dataclass
class ImageMetricResult:
    ssim: float = 0.0
    lpips_dist: float = float("nan")
    lpips_sim: float = 0.0
    ssim_ok: bool = False
    lpips_ok: bool = False


# ===================== LaTeX utils =====================

def extract_document_body(tex: str) -> str:
    m = re.search(r"\\begin\{document\}(.*)\\end\{document\}", tex, flags=re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else tex


def strip_latex_comments(tex: str) -> str:
    out_lines = []
    for line in tex.splitlines():
        i, cut = 0, None
        while i < len(line):
            if line[i] == "%":
                if i > 0 and line[i - 1] == "\\":
                    i += 1; continue
                cut = i; break
            i += 1
        if cut is not None:
            line = line[:cut]
        out_lines.append(line)
    return "\n".join(out_lines)


def normalize_tex(tex: str) -> str:
    tex = tex.replace("\r\n", "\n").replace("\r", "\n")
    tex = strip_latex_comments(tex)
    tex = re.sub(r"[ \t]+", " ", tex)
    tex = re.sub(r"\n{3,}", "\n\n", tex)
    return tex.strip()


# ===================== CrystalBLEU (ported from SciTikZ EasyR1) =====================

def _pad_sequence(sequence, n, pad_left=False, pad_right=False, left_pad_symbol=None, right_pad_symbol=None):
    sequence = iter(sequence)
    if pad_left:
        sequence = chain((left_pad_symbol,) * (n - 1), sequence)
    if pad_right:
        sequence = chain(sequence, (right_pad_symbol,) * (n - 1))
    return sequence


def _ngrams(sequence, n, **kwargs):
    sequence = _pad_sequence(sequence, n, **kwargs)
    iterables = tee(sequence, n)
    for i, sub_iterable in enumerate(iterables):
        for _ in range(i):
            next(sub_iterable, None)
    return zip(*iterables)


def _simple_bleu_fallback(ref_tokens: List[str], hyp_tokens: List[str], n: int = 4) -> float:
    if not ref_tokens or not hyp_tokens:
        return 0.0
    precisions = []
    for i in range(1, n + 1):
        ref_ngrams = Counter(_ngrams(ref_tokens, i))
        hyp_ngrams = Counter(_ngrams(hyp_tokens, i))
        if len(hyp_ngrams) == 0:
            precisions.append(0.0); continue
        matches = sum(min(ref_ngrams[ng], hyp_ngrams[ng]) for ng in hyp_ngrams)
        precisions.append(matches / len(hyp_ngrams))
    if all(p > 0 for p in precisions):
        bleu = math.exp(sum(math.log(p) for p in precisions) / len(precisions))
    else:
        bleu = 0.0
    ref_len, hyp_len = len(ref_tokens), len(hyp_tokens)
    bp = 1.0 if hyp_len > ref_len else (math.exp(1 - ref_len / hyp_len) if hyp_len > 0 else 0.0)
    return float(bp * bleu)


class CrystalBLEU:
    """CrystalBLEU for LaTeX/TikZ — TexLexer tokenize + MosesTokenizer for text-like tokens."""

    _fraction_warning_printed = False

    def __init__(self, corpus: List[str], k: int = 500, n: int = 4,
                 use_cache: bool = True, cache_dir: Optional[str] = None):
        if corpus_bleu is None:
            raise ImportError("crystalbleu not installed: pip install crystalbleu")
        if TexLexer is None or MosesTokenizer is None:
            raise ImportError("pygments + sacremoses required")
        self.lexer = TexLexer()
        self.tokenizer = MosesTokenizer()
        self.use_cache, self.corpus, self.k, self.n = bool(use_cache), list(corpus), int(k), int(n)
        self._cache_dir = Path(cache_dir or os.path.expanduser("~/.cache/crystalbleu_latex"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _is_comment_token(self, tt) -> bool:
        return (Comment is not None) and (tt in Comment)

    def _is_text_like_token(self, tt) -> bool:
        if Text is not None and tt in Text:
            return True
        if Name is not None and (tt in Name.Attribute or tt in Name.Builtin):
            return True
        return False

    def _tokenize(self, text: str) -> List[str]:
        tokens = []
        for tt, value in self.lexer.get_tokens(normalize_tex(text)):
            if not value or not value.strip() or self._is_comment_token(tt):
                continue
            v = value.strip()
            if not v:
                continue
            if self._is_text_like_token(tt):
                tokens.extend(self.tokenizer.tokenize(v))
            else:
                tokens.append(v)
        return tokens

    def _corpus_fingerprint(self) -> str:
        h = md5()
        h.update(f"k={self.k};n={self.n};len={len(self.corpus)}".encode())
        for s in self.corpus:
            ss = normalize_tex(s)
            b = ss.encode("utf-8", errors="ignore")
            h.update(len(b).to_bytes(8, "little", signed=False))
            h.update(b[:4096])
            h.update(md5(b).digest())
        return h.hexdigest()

    @cached_property
    def trivially_shared_ngrams(self) -> Dict:
        cache_file = self._cache_dir / f"trivial_{self._corpus_fingerprint()}.pkl"
        if self.use_cache and cache_file.is_file():
            with open(cache_file, "rb") as f:
                return load(f)
        freq = Counter()
        for tex in self.corpus:
            toks = self._tokenize(tex)
            if not toks: continue
            for o in range(1, self.n + 1):
                freq.update(_ngrams(toks, o))
        trivial = dict(freq.most_common(self.k))
        if self.use_cache:
            with open(cache_file, "wb") as f:
                dump(trivial, f)
        return trivial

    def score_sentence(self, ref: str, hyp: str) -> float:
        ref_toks = self._tokenize(ref)
        hyp_toks = self._tokenize(hyp)
        if not ref_toks or not hyp_toks:
            return 0.0
        try:
            s = float(corpus_bleu(list_of_references=[[ref_toks]], hypotheses=[hyp_toks],
                                   ignoring=self.trivially_shared_ngrams))
            return max(0.0, min(1.0, s))
        except Exception as e:
            es = str(e)
            if "_normalize" in es or "Fraction" in es:
                if not CrystalBLEU._fraction_warning_printed:
                    CrystalBLEU._fraction_warning_printed = True
                return _simple_bleu_fallback(ref_toks, hyp_toks, n=self.n)
            raise


# ===================== Token Edit Distance (ported from SciTikZ) =====================

class TokenEditDistance(ExtendedEditDistance):
    """EED over TeX tokens — Pygments TexLexer tokenize, then ExtendedEditDistance."""

    def __init__(self, *args, **kwargs):
        if ExtendedEditDistance is None:
            raise ImportError("torchmetrics required")
        if TexLexer is None:
            raise ImportError("pygments required")
        super().__init__(*args, **kwargs)
        self.lexer = TexLexer()

    @staticmethod
    def _is_comment(tt) -> bool:
        return (Comment is not None) and (tt in Comment)

    @staticmethod
    def _is_text(tt) -> bool:
        return (Text is not None) and (tt in Text)

    def tokenize_to_tokens(self, text: str, language: str) -> List[str]:
        tokens = []
        for tt, value in self.lexer.get_tokens(normalize_tex(text)):
            if not value or not value.strip() or self._is_comment(tt):
                continue
            v = value.strip()
            if not v: continue
            if self._is_text(tt):
                fn = _preprocess_en if language == "en" else _preprocess_ja
                tokens.extend(fn(v).split())
            else:
                tokens.extend(v.split())
        return tokens

    def _preprocess_sentences(self, preds, target, language):
        target, preds = _validate_inputs(hypothesis_corpus=preds, ref_corpus=target)
        def to_s(text):
            return " " + " ".join(self.tokenize_to_tokens(text, language)) + " "
        return [to_s(p) for p in preds], [[to_s(r) for r in refs] for refs in target]

    def update(self, preds, target):
        preds, target = self._preprocess_sentences(preds, target, self.language)
        if self.sentence_eed is None:
            self.sentence_eed = []
        if 0 in (len(preds), len(target[0])):
            return self.sentence_eed
        for hyp, tw in zip(preds, target):
            self.sentence_eed.append(
                _compute_sentence_statistics(hyp, tw, self.alpha, self.rho, self.deletion, self.insertion))
        return self.sentence_eed

    def compute(self, *args, **kwargs):
        return super().compute(*args, **kwargs).item()


def _eed_dist_to_sim(dist_norm: float, tau: float = 0.4) -> float:
    if not math.isfinite(dist_norm) or tau <= 0:
        return 0.0
    return float(math.exp(-max(0.0, float(dist_norm)) / tau))


# ===================== image utils (ported from SciTikZ image_metrics.py) =====================

def _safe_open_rgb(path: str) -> Image.Image:
    img = Image.open(path)
    return img if img.mode == "RGB" else img.convert("RGB")


def _trim_white_border(img: Image.Image, bg_color=(255,255,255), pad: int = 2) -> Image.Image:
    if img.mode != "RGB":
        img = img.convert("RGB")
    bg = Image.new("RGB", img.size, bg_color)
    diff = ImageChops.difference(img, bg).convert("L")
    bbox = diff.getbbox()
    if bbox is None:
        return img
    left, upper, right, lower = bbox
    return img.crop((max(0, left-pad), max(0, upper-pad),
                     min(img.width, right+pad), min(img.height, lower+pad)))


def _pad_to_size(img: Image.Image, target_w: int, target_h: int, fill=(255,255,255)) -> Image.Image:
    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width == target_w and img.height == target_h:
        return img
    out = Image.new("RGB", (target_w, target_h), fill)
    out.paste(img, ((target_w - img.width)//2, (target_h - img.height)//2))
    return out


# ===================== top-level wrappers =====================

class AcademicCodeMetrics:
    """Compute TED + CrystalBLEU for a (gt_tex, pred_tex) pair."""

    def __init__(self, gt_corpus: List[str]):
        if TexLexer is None:
            raise ImportError("pygments required: pip install pygments")
        self.cb = CrystalBLEU(corpus=gt_corpus)
        self.ted = TokenEditDistance(language="en", alpha=2.0, rho=0.3, deletion=0.2, insertion=1.0)

    def compute(self, gt_tex: str, pred_tex: str) -> CodeMetricResult:
        gt_body = normalize_tex(extract_document_body(gt_tex))
        pr_body = normalize_tex(extract_document_body(pred_tex))
        self.ted.reset()
        d_norm = float(self.ted(preds=[pr_body], target=[[gt_body]]))
        if not math.isfinite(d_norm):
            d_norm = float("nan")
        try:
            ref_len = max(len(self.ted.tokenize_to_tokens(gt_body, language="en")), 1)
        except Exception:
            ref_len = 1
        ted_dist = d_norm * ref_len if math.isfinite(d_norm) else float("nan")
        ted_sim = _eed_dist_to_sim(d_norm)
        cb = float(self.cb.score_sentence(gt_body, pr_body))
        return CodeMetricResult(
            ted_dist=ted_dist, ted_dist_norm=d_norm, ted_sim=ted_sim,
            crystalbleu=cb,
        )


class AcademicImageMetrics:
    """Compute SSIM + LPIPS for a (gt_img_path, pred_img_path) pair.  CPU-safe."""

    def __init__(self, device: str = "cpu", lpips_tau: float = 0.5):
        self.device = torch.device(device)
        self.lpips_tau = float(lpips_tau)
        self.lpips_model = None
        if _lpips_lib is not None:
            self.lpips_model = _lpips_lib.LPIPS(net="alex").to(self.device)
            self.lpips_model.eval()
        self._lpips_tf = T.Compose([
            T.Resize((384, 384), interpolation=T.InterpolationMode.BICUBIC),
            T.ToTensor(),
            T.Lambda(lambda x: x * 2.0 - 1.0),
        ])
        self._to_tensor = T.ToTensor()

    @torch.no_grad()
    def compute(self, gt_path: str, pred_path: str) -> ImageMetricResult:
        r = ImageMetricResult()
        gt = _safe_open_rgb(gt_path)
        pr = _safe_open_rgb(pred_path)

        # --- SSIM ---
        if ssim_fn is not None:
            try:
                gt_t = _trim_white_border(gt)
                pr_t = _trim_white_border(pr)
                gw, gh = gt_t.size; pw, ph = pr_t.size
                tw, th = max(gw, pw), max(gh, ph)
                gt_t = _pad_to_size(gt_t, tw, th)
                pr_t = _pad_to_size(pr_t, tw, th)
                gt_ts = self._to_tensor(gt_t).unsqueeze(0).to(self.device)
                pr_ts = self._to_tensor(pr_t).unsqueeze(0).to(self.device)
                r.ssim = float(ssim_fn(gt_ts, pr_ts, data_range=1.0, size_average=True))
                r.ssim_ok = True
            except Exception:
                pass

        # --- LPIPS ---
        if self.lpips_model is not None:
            try:
                gt_l = self._lpips_tf(gt).unsqueeze(0).to(self.device)
                pr_l = self._lpips_tf(pr).unsqueeze(0).to(self.device)
                d = self.lpips_model(gt_l, pr_l).item()
                r.lpips_dist = float(d)
                r.lpips_sim = float(math.exp(-d / self.lpips_tau)) if self.lpips_tau > 0 else 0.0
                r.lpips_ok = True
            except Exception:
                pass

        return r
