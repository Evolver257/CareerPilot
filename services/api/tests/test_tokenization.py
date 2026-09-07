from app.llm.tokenization import (
    APPROXIMATE_TOKEN_COUNTER,
    CallableTokenCounter,
    max_prefix_end,
    token_counter_for_provider,
)


def test_provider_token_counter_is_selected_and_labelled_exact() -> None:
    class Provider:
        tokenizer_signature = "qwen:test-revision:Qwen2Tokenizer"

        @staticmethod
        def count_embedding_tokens(text: str) -> int:
            return len(text) * 2

    counter = token_counter_for_provider(Provider())

    assert counter.exact is True
    assert counter.signature == "qwen:test-revision:Qwen2Tokenizer"
    assert counter.count("岗位") == 4


def test_provider_without_tokenizer_uses_explicit_approximation() -> None:
    counter = token_counter_for_provider(object())

    assert counter is APPROXIMATE_TOKEN_COUNTER
    assert counter.exact is False
    assert counter.signature.startswith("approximate:")


def test_max_prefix_end_preserves_source_and_both_limits() -> None:
    counter = CallableTokenCounter(callback=len, signature="test:chars", exact=True)
    text = "abcdefghijklmnopqrstuvwxyz"

    end = max_prefix_end(text, max_chars=20, max_tokens=7, counter=counter)

    assert text[:end] == "abcdefg"
    assert counter.count(text[:end]) <= 7
