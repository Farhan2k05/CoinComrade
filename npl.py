import spacy
from spacy.cli import download
import re

def load_model():
    try:
        return spacy.load("en_core_web_sm")
    except OSError:
        download("en_core_web_sm")
        return spacy.load("en_core_web_sm")

nlp = load_model()

IGNORE = {
    "ml", "g", "kg", "l", "x", "pk", "pack", "pcs", "twin", "pair",
    "plus", "v", "power", "single", "family", "loose", "bunch",
    "box", "tin", "can", "tub", "jar"
}

def clean_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def basic_clean(item_name: str) -> str:
    text = clean_text(item_name)

    doc = nlp(text)
    tokens = [
        token.lemma_ for token in doc
        if token.is_alpha
        and not token.is_stop
        and token.pos_ in {"NOUN", "PROPN"}
        and token.lemma_ not in IGNORE
        and len(token.lemma_) > 2
    ]

    if tokens:
        return tokens[-1].upper()

    words = [w for w in text.split() if w not in IGNORE]
    return (words[0] if words else item_name).upper()