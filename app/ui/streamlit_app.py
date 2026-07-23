from __future__ import annotations

import os
import time
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
    token = st.session_state.get("api_token") or os.getenv("STREAMLIT_API_TOKEN", "")
    return ContractAPIClient(base_url=base_url, api_token=token.strip() or None)


def init_state() -> None:
    defaults = {
        "contract_id": "",
        "ai_provider": "ollama",
        "ollama_model": "llama3.1:8b",
        "openai_model": "gpt-5",
        "api_token": os.getenv("STREAMLIT_API_TOKEN", ""),
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
        token = st.text_input(
            "API token",
            value=st.session_state.api_token,
            type="password",
            help="Required when AUTH_ENABLED=true on the FastAPI backend.",
        )
        st.session_state.api_token = token.strip()
        client.api_token = st.session_state.api_token or None
        try:
            health = client.health()
        except APIClientError as exc:
            render_error(exc)
            return
        st.success("FastAPI is online")
        st.metric("LLM", health.get("model", "unknown"))
        st.caption(f"Provider: {health.get('llm_provider', 'unknown')}")
        st.caption(f"Embeddings: {health.get('embedding_provider', 'unknown')}")
        st.caption(f"Storage: {health.get('storage_backend', 'unknown')}")
        st.caption(f"Jobs: {health.get('job_backend', 'unknown')}")
        if health.get("auth_enabled"):
            st.warning("API authentication is enabled.")
        st.caption(f"{health.get('app_name', 'Contract AI Assistant')} {health.get('version', '')}")

        provider = st.segmented_control(
            "AI provider",
            options=["ollama", "openai"],
            format_func=lambda value: "Ollama" if value == "ollama" else "GPT/OpenAI",
            default=st.session_state.ai_provider,
        )
        st.session_state.ai_provider = provider or "ollama"
        if st.session_state.ai_provider == "ollama":
            st.session_state.ollama_model = st.text_input(
                "Ollama model",
                value=st.session_state.ollama_model,
            ).strip()
        else:
            st.session_state.openai_model = st.text_input(
                "OpenAI model",
                value=st.session_state.openai_model,
            ).strip()

        contract_id = st.text_input(
            "Contract ID",
            value=st.session_state.contract_id,
            placeholder="Upload a contract or paste an ID",
        )
        if contract_id != st.session_state.contract_id:
            st.session_state.contract_id = contract_id.strip()


def selected_llm() -> tuple[str, str]:
    provider = st.session_state.ai_provider
    if provider == "openai":
        return provider, st.session_state.openai_model or "gpt-5"
    return provider, st.session_state.ollama_model or "llama3.1:8b"


def render_upload(client: ContractAPIClient) -> None:
    st.subheader("Upload Contract")
    uploaded_file = st.file_uploader("PDF contract", type=["pdf"])
    use_ai = st.toggle("Use AI to refine extracted clauses", value=False)
    use_async = st.toggle("Use background upload", value=True)
    with st.expander("Contract metadata"):
        col_a, col_b = st.columns(2)
        with col_a:
            contract_type = st.text_input("Contract type", placeholder="MSA, NDA, SOW")
            jurisdiction = st.text_input("Jurisdiction", placeholder="New York")
            governing_law = st.text_input("Governing law", placeholder="Laws of New York")
        with col_b:
            effective_date = st.text_input("Effective date", placeholder="2026-07-22")
            renewal_term = st.text_input("Renewal term", placeholder="One year")
            customer = st.text_input("Customer", placeholder="Customer legal name")
            supplier = st.text_input("Supplier", placeholder="Supplier legal name")

    if st.button("Upload and index", type="primary", disabled=uploaded_file is None):
        if uploaded_file is None:
            return
        llm_provider, llm_model = selected_llm()
        metadata = {
            "contract_type": contract_type.strip() or None,
            "jurisdiction": jurisdiction.strip() or None,
            "governing_law": governing_law.strip() or None,
            "effective_date": effective_date.strip() or None,
            "renewal_term": renewal_term.strip() or None,
            "customer": customer.strip() or None,
            "supplier": supplier.strip() or None,
        }
        with st.spinner("Extracting clauses and indexing the contract..."):
            try:
                if use_async:
                    job_response = client.upload_contract_async(
                        filename=uploaded_file.name,
                        content=uploaded_file.getvalue(),
                        content_type=uploaded_file.type or "application/pdf",
                        use_ai=use_ai,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        metadata=metadata,
                    )
                    response = poll_upload_job(client, job_response["job"]["id"])
                else:
                    response = client.upload_contract(
                        filename=uploaded_file.name,
                        content=uploaded_file.getvalue(),
                        content_type=uploaded_file.type or "application/pdf",
                        use_ai=use_ai,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        metadata=metadata,
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
        metadata = contract.get("metadata") or {}
        if any(metadata.values()):
            st.json({key: value for key, value in metadata.items() if value})
        render_agent_trace(st.session_state.upload_response.get("agent_trace", []))


def poll_upload_job(client: ContractAPIClient, job_id: str) -> dict[str, Any]:
    status_slot = st.empty()
    for _ in range(90):
        job = client.get_job(job_id)["job"]
        status = job["status"]
        status_slot.info(f"Upload job {job_id}: {status}")
        if status == "succeeded":
            status_slot.success("Background upload completed")
            return job["result"]
        if status == "failed":
            raise APIClientError(job.get("error") or "Background upload failed.", code="job_failed")
        time.sleep(1)
    raise APIClientError("Background upload is still running. Check the job status later.")


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
        llm_provider, llm_model = selected_llm()
        with st.spinner("Analyzing contract risk..."):
            try:
                st.session_state.risks_response = client.analyze_risks(
                    contract_id,
                    use_llm,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                )
            except APIClientError as exc:
                render_error(exc)
                return

    response = st.session_state.risks_response
    if not response:
        return

    st.metric("Overall risk", response["overall_risk_level"].title())
    st.write(response["executive_summary"])
    render_list("Compliance findings", response.get("compliance_findings", []))
    render_list("Negotiation recommendations", response.get("negotiation_recommendations", []))
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
    render_agent_trace(response.get("agent_trace", []))


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
        llm_provider, llm_model = selected_llm()
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
                    llm_provider=llm_provider,
                    llm_model=llm_model,
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
    render_list("Compliance notes", response.get("compliance_notes", []))
    render_list("Negotiation strategy", response.get("negotiation_strategy", []))
    if response.get("recommended_clause"):
        st.text_area("Recommended clause", value=response["recommended_clause"], height=180)
    render_agent_trace(response.get("agent_trace", []))


def render_ask(client: ContractAPIClient) -> None:
    st.subheader("Ask the Contract")
    contract_id = st.session_state.contract_id.strip()
    if not contract_id:
        st.info("Upload a contract or paste a contract ID in the sidebar.")
        return

    top_k = st.slider("Sources", min_value=1, max_value=12, value=5)
    use_llm = st.toggle("Use AI answer generation", value=False)
    with st.expander("Retrieval filters"):
        filter_contract_type = st.text_input("Filter contract type", key="ask_filter_contract_type")
        filter_jurisdiction = st.text_input("Filter jurisdiction", key="ask_filter_jurisdiction")

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
            llm_provider, llm_model = selected_llm()
            metadata_filters = {
                key: value
                for key, value in {
                    "contract_type": filter_contract_type.strip(),
                    "jurisdiction": filter_jurisdiction.strip(),
                }.items()
                if value
            }
            try:
                response = client.ask_contract(
                    contract_id,
                    question,
                    top_k,
                    use_llm,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    metadata_filters=metadata_filters,
                )
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
        render_agent_trace(response.get("agent_trace", []))
        st.session_state.messages.append({"role": "assistant", "content": response["answer"]})


def render_list(title: str, items: list[str]) -> None:
    if not items:
        return
    st.markdown(f"**{title}**")
    for item in items:
        st.write(f"- {item}")


def render_agent_trace(trace: list[dict[str, Any]]) -> None:
    if not trace:
        return
    with st.expander("Agent trace"):
        for item in trace:
            st.markdown(f"**{item['agent_name']}**")
            st.caption(item["summary"])


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
