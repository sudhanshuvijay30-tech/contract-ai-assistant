from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

import streamlit as st

from app.schemas.contracts import ClauseType
from app.ui.api_client import (
    APIClientError,
    ContractAPIClient,
    missing_openai_help,
)

RISK_COLORS = {
    "low": "#1f9d55",
    "medium": "#b7791f",
    "high": "#c05621",
    "critical": "#c53030",
}


def get_api_client() -> ContractAPIClient:
    base_url = os.getenv("STREAMLIT_API_BASE_URL", "http://localhost:8000")
    return ContractAPIClient(base_url=base_url)


def init_state() -> None:
    defaults = {
        "contract_id": "",
        "upload_response": None,
        "clauses_response": None,
        "risks_response": None,
        "messages": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def render_error(error: APIClientError) -> None:
    help_text = missing_openai_help(error)
    if help_text:
        st.error(help_text)
        return
    status = f" HTTP {error.status_code}." if error.status_code else ""
    st.error(f"{error.message}{status}")


def render_status(client: ContractAPIClient) -> None:
    with st.sidebar:
        st.header("Connection")
        st.caption(client.base_url)
        try:
            health = client.health()
        except APIClientError as exc:
            render_error(exc)
            return
        st.success("FastAPI is online")
        st.metric("LLM", health.get("model", "unknown"))
        st.caption(f"Provider: {health.get('llm_provider', 'unknown')}")
        st.caption(f"Embeddings: {health.get('embedding_provider', 'unknown')}")
        st.caption(f"{health.get('app_name', 'Contract AI Assistant')} {health.get('version', '')}")

        contract_id = st.text_input(
            "Contract ID",
            value=st.session_state.contract_id,
            placeholder="Upload a contract or paste an ID",
        )
        if contract_id != st.session_state.contract_id:
            st.session_state.contract_id = contract_id.strip()


def render_upload(client: ContractAPIClient) -> None:
    st.subheader("Upload Contract")
    uploaded_file = st.file_uploader("PDF contract", type=["pdf"])
    use_ai = st.toggle("Use AI to refine extracted clauses", value=False)

    if st.button("Upload and index", type="primary", disabled=uploaded_file is None):
        if uploaded_file is None:
            return
        with st.spinner("Extracting clauses and indexing the contract..."):
            try:
                response = client.upload_contract(
                    filename=uploaded_file.name,
                    content=uploaded_file.getvalue(),
                    content_type=uploaded_file.type or "application/pdf",
                    use_ai=use_ai,
                )
            except APIClientError as exc:
                render_error(exc)
                return
        st.session_state.upload_response = response
        st.session_state.contract_id = response["contract"]["id"]
        st.session_state.clauses_response = None
        st.session_state.risks_response = None
        st.success("Contract uploaded")

    if st.session_state.upload_response:
        contract = st.session_state.upload_response["contract"]
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Contract ID", contract["id"])
        col_b.metric("Pages", contract["page_count"])
        col_c.metric("Clauses", st.session_state.upload_response["clauses_count"])
        st.code(contract["id"], language="text")


def render_clauses(client: ContractAPIClient) -> None:
    st.subheader("Clauses")
    contract_id = st.session_state.contract_id.strip()
    if not contract_id:
        st.info("Upload a contract or paste a contract ID in the sidebar.")
        return

    if st.button("Load clauses"):
        with st.spinner("Loading extracted clauses..."):
            try:
                st.session_state.clauses_response = client.list_clauses(contract_id)
            except APIClientError as exc:
                render_error(exc)
                return

    response = st.session_state.clauses_response
    if not response:
        return

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for clause in response["clauses"]:
        grouped[clause["type"]].append(clause)

    for clause_type, clauses in sorted(grouped.items()):
        with st.expander(f"{format_label(clause_type)} ({len(clauses)})", expanded=True):
            for clause in clauses:
                page = page_label(clause)
                st.markdown(f"**{clause['title']}** {page}")
                st.caption(f"{clause['id']} | confidence {clause['confidence']:.0%}")
                st.write(clause["text"])
                st.divider()


def render_risks(client: ContractAPIClient) -> None:
    st.subheader("Risk Analysis")
    contract_id = st.session_state.contract_id.strip()
    if not contract_id:
        st.info("Upload a contract or paste a contract ID in the sidebar.")
        return

    use_llm = st.toggle("Use AI risk analysis", value=False)
    if st.button("Analyze risks", type="primary"):
        with st.spinner("Analyzing contract risk..."):
            try:
                st.session_state.risks_response = client.analyze_risks(contract_id, use_llm)
            except APIClientError as exc:
                render_error(exc)
                return

    response = st.session_state.risks_response
    if not response:
        return

    st.metric("Overall risk", response["overall_risk_level"].title())
    st.write(response["executive_summary"])
    for risk in response["risks"]:
        color = RISK_COLORS.get(risk["level"], "#4a5568")
        st.markdown(
            f"<span style='background:{color};color:white;padding:4px 8px;"
            f"border-radius:4px;font-size:12px'>{risk['level'].upper()}</span> "
            f"**{risk['title']}**",
            unsafe_allow_html=True,
        )
        st.write(risk["summary"])
        st.caption(risk["rationale"])
        st.info(risk["recommendation"])
        if risk["evidence"]:
            with st.expander("Evidence"):
                for evidence in risk["evidence"]:
                    st.write(evidence)
        st.divider()


def render_compare(client: ContractAPIClient) -> None:
    st.subheader("Clause Comparison")
    col_a, col_b = st.columns(2)
    with col_a:
        source_title = st.text_input("Source title", value="Preferred clause")
        source_type = st.selectbox("Source type", clause_type_options(), key="source_type")
        source_text = st.text_area("Source clause", height=220)
    with col_b:
        counterparty_title = st.text_input("Counterparty title", value="Counterparty clause")
        counterparty_type = st.selectbox(
            "Counterparty type",
            clause_type_options(),
            key="counterparty_type",
        )
        counterparty_text = st.text_area("Counterparty clause", height=220)

    preferred_position = st.text_area("Preferred position", height=90)
    use_llm = st.toggle("Use AI comparison", value=False)
    ready = len(source_text.strip()) >= 10 and len(counterparty_text.strip()) >= 10

    if st.button("Compare clauses", type="primary", disabled=not ready):
        with st.spinner("Comparing clause positions..."):
            try:
                response = client.compare_clauses(
                    source_clause={
                        "title": source_title,
                        "type": source_type,
                        "text": source_text,
                    },
                    counterparty_clause={
                        "title": counterparty_title,
                        "type": counterparty_type,
                        "text": counterparty_text,
                    },
                    preferred_position=preferred_position,
                    use_llm=use_llm,
                )
            except APIClientError as exc:
                render_error(exc)
                return
        render_comparison_response(response)


def render_comparison_response(response: dict[str, Any]) -> None:
    col_a, col_b = st.columns(2)
    col_a.metric("Alignment", f"{response['alignment_score']:.0%}")
    col_b.metric("Risk delta", response["risk_delta"].title())
    st.write(response["summary"])
    render_list("Missing terms", response["missing_terms"])
    render_list("Material deviations", response["material_deviations"])
    render_list("Negotiation points", response["negotiation_points"])
    if response.get("recommended_clause"):
        st.text_area("Recommended clause", value=response["recommended_clause"], height=180)


def render_ask(client: ContractAPIClient) -> None:
    st.subheader("Ask the Contract")
    contract_id = st.session_state.contract_id.strip()
    if not contract_id:
        st.info("Upload a contract or paste a contract ID in the sidebar.")
        return

    top_k = st.slider("Sources", min_value=1, max_value=12, value=5)
    use_llm = st.toggle("Use AI answer generation", value=False)

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    question = st.chat_input("Ask about obligations, risk, payment, termination, or liability")
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Reading relevant clauses..."):
            try:
                response = client.ask_contract(contract_id, question, top_k, use_llm)
            except APIClientError as exc:
                render_error(exc)
                return
        st.write(response["answer"])
        if response["sources"]:
            with st.expander("Sources"):
                for source in response["sources"]:
                    st.markdown(f"**{source['title']}** {page_label(source)}")
                    st.caption(f"{source['clause_id']} | score {source.get('score')}")
                    st.write(source["text"])
        st.session_state.messages.append({"role": "assistant", "content": response["answer"]})


def render_list(title: str, items: list[str]) -> None:
    if not items:
        return
    st.markdown(f"**{title}**")
    for item in items:
        st.write(f"- {item}")


def clause_type_options() -> list[str]:
    return [clause_type.value for clause_type in ClauseType]


def format_label(value: str) -> str:
    return value.replace("_", " ").title()


def page_label(item: dict[str, Any]) -> str:
    start = item.get("page_start")
    end = item.get("page_end")
    if start and end and start != end:
        return f"pages {start}-{end}"
    if start:
        return f"page {start}"
    return ""


def main() -> None:
    st.set_page_config(page_title="Contract AI Assistant", page_icon=None, layout="wide")
    init_state()
    client = get_api_client()
    render_status(client)

    st.title("Contract AI Assistant")
    st.caption("Upload, review, compare, and question contracts through the FastAPI backend.")

    upload_tab, clauses_tab, risks_tab, compare_tab, ask_tab = st.tabs(
        ["Upload", "Clauses", "Risks", "Compare", "Ask"]
    )
    with upload_tab:
        render_upload(client)
    with clauses_tab:
        render_clauses(client)
    with risks_tab:
        render_risks(client)
    with compare_tab:
        render_compare(client)
    with ask_tab:
        render_ask(client)


if __name__ == "__main__":
    main()
