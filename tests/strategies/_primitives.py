"""Leaf strategies shared by the document strategies."""

from hypothesis import strategies as st

safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "Zs"), whitelist_characters="-_./:()"
    ),
    max_size=40,
)
"""Text with no character that any supported encoding treats specially."""

nonempty_text = safe_text.filter(lambda s: s.strip())
"""`safe_text` that is not blank, for fields a parser requires to be present."""

json_leaf = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    safe_text,
)
"""Any scalar JSON value, in ranges that survive a JSON round trip exactly."""

identifier = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=24,
).filter(lambda s: s[0].isalpha())
"""A name usable as a property, schema, or operation identifier."""

media_type_str = st.builds(
    lambda t, s: f"{t}/{s}",
    st.sampled_from(["application", "text", "image", "audio", "video", "model", "font"]),
    identifier,
)
"""Any syntactically valid media type string."""
