import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google import genai
from openai import OpenAI

from .token_utils import estimate_tokens, split_sentences, trim_to_token_budget

load_dotenv()

OFFICIAL_INDIAN_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "as": "Assamese",
    "bn": "Bengali",
    "brx": "Bodo",
    "doi": "Dogri",
    "gu": "Gujarati",
    "hi": "Hindi",
    "kn": "Kannada",
    "ks": "Kashmiri",
    "kok": "Konkani",
    "mai": "Maithili",
    "ml": "Malayalam",
    "mni": "Manipuri",
    "mr": "Marathi",
    "ne": "Nepali",
    "or": "Odia",
    "pa": "Punjabi",
    "sa": "Sanskrit",
    "sat": "Santali",
    "sd": "Sindhi",
    "ta": "Tamil",
    "te": "Telugu",
    "ur": "Urdu",
}

EDUCATION_STYLE_GUIDANCE: Dict[str, str] = {
    "high school": "Use very plain language, short sentences, and practical examples.",
    "diploma": "Use plain language with light technical terms only when necessary.",
    "bachelor": "Use clear professional language with moderate detail.",
    "master": "Use concise analytical language with stronger policy nuance.",
    "doctorate": "Use expert-level but readable policy analysis.",
}

class AIExplanationEngine:
    def __init__(self, provider: str = "google"):
        self.provider = provider
        self.model_id = "gemini-2.5-flash"
        if provider == "openai":
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        else:
            self.client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    @staticmethod
    def is_supported_language(language_code: str) -> bool:
        return (language_code or "").lower() in OFFICIAL_INDIAN_LANGUAGES

    @staticmethod
    def get_language_name(language_code: str) -> str:
        return OFFICIAL_INDIAN_LANGUAGES.get((language_code or "").lower(), "English")

    @staticmethod
    def get_supported_languages() -> List[Dict[str, str]]:
        return [{"code": code, "name": name} for code, name in OFFICIAL_INDIAN_LANGUAGES.items()]

    @staticmethod
    def _build_profile_prompt_block(user_profile: Optional[Dict[str, Any]]) -> str:
        profile = user_profile or {}

        profession = profile.get("profession") or "Citizen"
        education_level = (profile.get("educationLevel") or "Bachelor").strip()
        years_experience = profile.get("yearsExperience")
        region = profile.get("region") or "Not specified"
        industry = profile.get("industry") or "Not specified"
        interests = profile.get("interests") or []

        guidance = EDUCATION_STYLE_GUIDANCE.get(
            education_level.lower(),
            "Use clear language with balanced detail and minimal jargon.",
        )

        interest_text = ", ".join(interests) if interests else "None specified"
        experience_text = f"{years_experience} years" if years_experience is not None else "Not specified"

        return (
            "Citizen profile for personalization:\n"
            f"- Profession: {profession}\n"
            f"- Education Level: {education_level}\n"
            f"- Years of Experience: {experience_text}\n"
            f"- Region: {region}\n"
            f"- Industry: {industry}\n"
            f"- Interests: {interest_text}\n"
            f"- Explanation depth guidance: {guidance}\n"
        )

    def generate_explanation(
        self,
        query: str,
        context_chunks: List[Dict],
        document_title: str = "",
        user_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context_text = ""
        context_token_total = 0
        for idx, chunk in enumerate(context_chunks, start=1):
            chapter_label = (chunk.get('metadata') or {}).get('chapter')
            chapter_label = (chapter_label or "").strip()

            if chapter_label:
                if chapter_label.lower().startswith("chapter"):
                    citation_token = chapter_label
                else:
                    citation_token = f"Chapter {chapter_label}"
            else:
                citation_token = f"Context {idx}"

            chunk_header = (
                f"\n[Context {idx} | Document: {chunk['metadata'].get('document_name')}"
                f" | Section: {chunk['metadata'].get('chapter')}]\n"
            )
            context_text += chunk_header
            context_text += f"Citation to use: [{citation_token}]\n"
            context_text += f"Clause/Section Text: {chunk['content']}\n"
            context_token_total += estimate_tokens(chunk['content'])

        profile_block = self._build_profile_prompt_block(user_profile)

        system_prompt = """
        You are a legal AI that explains Indian laws in simple words. Your job is to help citizens understand what laws say.

        CRITICAL CITATION RULE:
        - Every factual sentence MUST end with exactly one citation in brackets.
        - Allowed citation formats: [Section ...], [Article ...], [Chapter ...], [Context ...].
        - Prefer [Section ...] / [Article ...] when the number is present in the law text.
        - If section/article numbers are not visible, use the provided "Citation to use" tokens.
        - Only tell facts that are in the context given to you.
        - If you cannot find something in the context, do NOT mention it.
        - Do NOT make up information.
        - Do NOT guess or assume.

        LANGUAGE RULE:
        - Use very simple words. Think of explaining to a 13-year-old.
        - Write short sentences. One idea per sentence.
        - Use common words. Avoid legal jargon when possible.
        - When you must use legal words, explain them in brackets.

        PERSONALIZATION RULE:
        - Remember the person's job, education level, and interests.
        - Give examples that matter to them.
        - Keep explanations at their level.

        STRUCTURE:
        - Start with "What it means" section
        - Then "What this means for you" section
        - End with "Key points" as a simple list

        Do NOT give legal advice. Only explain what the law says.
        """

        user_prompt = f"""
        Document: "{document_title or 'Uploaded legislative document'}"

        Question: "{query}"

        Person Profile:
        {profile_block}
        
        The Law (these are the facts you can use):
        {context_text}
        
        Rules for your answer:
        1. Use ONLY the law text above. Nothing else.
          2. Every factual sentence MUST end with one bracketed citation.
              Use the "Citation to use" token that appears above the clause you used.
        3. If something is not clearly shown in the law above, leave it out.
        4. Use simple words a 13-year-old would understand.
        5. Keep sentences short and clear.
        6. Do NOT give legal advice.
        7. Do NOT make promises about outcomes.

        Now explain the answer:
        """

        token_metrics = {
            "query_tokens_estimate": estimate_tokens(query),
            "context_tokens_estimate": context_token_total,
            "system_prompt_tokens_estimate": estimate_tokens(system_prompt),
            "user_prompt_tokens_estimate": estimate_tokens(user_prompt),
        }
        token_metrics["total_prompt_tokens_estimate"] = (
            token_metrics["system_prompt_tokens_estimate"]
            + token_metrics["user_prompt_tokens_estimate"]
        )

        if self.provider == "openai":
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            explanation = response.choices[0].message.content

            if getattr(response, "usage", None):
                token_metrics["provider_prompt_tokens"] = getattr(response.usage, "prompt_tokens", None)
                token_metrics["provider_completion_tokens"] = getattr(response.usage, "completion_tokens", None)

            token_metrics["response_tokens_estimate"] = estimate_tokens(explanation)
            return {
                "explanation": explanation,
                "token_metrics": token_metrics,
            }

        if self.provider == "google":
            full_prompt = f"{system_prompt}\n\n{user_prompt}"
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=full_prompt
            )
            explanation = response.text or ""

            usage_metadata = getattr(response, "usage_metadata", None)
            if usage_metadata:
                token_metrics["provider_prompt_tokens"] = getattr(usage_metadata, "prompt_token_count", None)
                token_metrics["provider_completion_tokens"] = getattr(usage_metadata, "candidates_token_count", None)

            token_metrics["response_tokens_estimate"] = estimate_tokens(explanation)
            return {
                "explanation": explanation,
                "token_metrics": token_metrics,
            }

        raise RuntimeError(f"Unsupported AI provider: {self.provider}")

    # Translation now handled by deep-translator in main.py
    # No LLM tokens spent on translation - uses free Google Translate API

    def summarize_chapter(self, chapter_text: str, max_tokens: int = 140) -> str:
        sentences = split_sentences(chapter_text)
        if not sentences:
            return trim_to_token_budget(chapter_text, max_tokens)

        selected_sentences = []
        for sentence in sentences[:3]:
            selected_sentences.append(sentence)
            candidate_summary = " ".join(selected_sentences)
            if estimate_tokens(candidate_summary) >= int(max_tokens * 0.85):
                break

        return trim_to_token_budget(" ".join(selected_sentences), max_tokens)
