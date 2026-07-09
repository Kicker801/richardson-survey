from datetime import datetime
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from typing import List
import os
import smtplib

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Frame, PageTemplate, Paragraph, SimpleDocTemplate, Spacer

load_dotenv(Path(__file__).with_name('.env'))

app = FastAPI(title='Richardson Survey Email Sender')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['POST', 'GET', 'OPTIONS'],
    allow_headers=['*'],
)

SURVEY_SMTP_USER = os.getenv('SURVEY_SMTP_USER', '')
SURVEY_SMTP_APP_PASSWORD = os.getenv('SURVEY_SMTP_APP_PASSWORD', '')
SURVEY_TO_EMAIL = os.getenv('SURVEY_TO_EMAIL', 'guydie10@gmail.com')


class SurveyAnswer(BaseModel):
    label: str
    value: str


class SurveySubmission(BaseModel):
    answers: List[SurveyAnswer]


def score_lead(answers: List[SurveyAnswer]):
    values = {a.label: a.value for a in answers}
    score = 0
    breakdown = []

    def add(points, reason):
        nonlocal score
        if points:
            score += points
            breakdown.append(f'{reason} (+{points})')

    qty_map = {'Under 72': 5, '72-143': 10, '144-287': 15, '288-575': 20, '576+': 25}
    qty_val = values.get('Estimated quantity for your FIRST order', '')
    add(qty_map.get(qty_val, 0), f'First order quantity: {qty_val}' if qty_val else '')

    reorder_map = {
        'One-time order': 0, 'Quarterly': 10, 'Monthly': 15,
        'Seasonal Drops': 12, 'Ongoing / Continuous Production': 20,
    }
    reorder_val = values.get('Estimated reorder frequency', '')
    add(reorder_map.get(reorder_val, 0), f'Reorder frequency: {reorder_val}' if reorder_val else '')

    budget_map = {'Under $1,000': 2, '$1,000-$5,000': 8, '$5,000-$10,000': 14, '$10,000+': 20}
    budget_val = values.get('What is your approximate yearly budget for custom hats?', '')
    add(budget_map.get(budget_val, 0), f'Budget: {budget_val}' if budget_val else '')

    timeline_map = {'1-2 months': 10, '3-6 months': 6, '6-12 months': 3}
    timeline_val = values.get('What is your desired timeline for your initial order?', '')
    add(timeline_map.get(timeline_val, 0), f'Timeline: {timeline_val}' if timeline_val else '')

    artwork_map = {'Yes': 10, 'In Progress': 5, 'No': 0}
    artwork_val = values.get('Do you already have artwork/logo files ready?', '')
    add(artwork_map.get(artwork_val, 0), f'Artwork ready: {artwork_val}' if artwork_val else '')

    type_map = {
        'Established Brand': 10, 'Corporate Business': 10, 'Retail Store': 8,
        'Clothing Brand': 8, 'Marketing / Promotional Company': 8,
        'Event / Organization': 6, 'Startup / New Brand': 4, 'Influencer / Creator Brand': 4,
    }
    type_val = values.get('What best describes your business?', '')
    selected_types = [t.strip() for t in type_val.split(',') if t.strip()]
    type_points = max((type_map.get(t, 0) for t in selected_types), default=0)
    add(type_points, f'Business type: {type_val}' if type_val else '')

    selling_val = values.get('Do you currently sell hats or apparel?', '')
    add(5 if selling_val == 'Yes' else 0, 'Already selling hats/apparel' if selling_val == 'Yes' else '')

    score = min(score, 100)

    if score >= 70:
        tier = 'HOT LEAD'
    elif score >= 40:
        tier = 'WARM LEAD'
    else:
        tier = 'COLD LEAD'

    return score, tier, breakdown


def build_pdf(answers: List[SurveyAnswer], score: int, tier: str) -> bytes:
    buffer = BytesIO()
    page_width, page_height = letter
    margin = 42
    gutter = 18
    title_height = 104
    column_width = (page_width - (margin * 2) - gutter) / 2
    column_height = page_height - (margin * 2) - title_height

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )

    left_frame = Frame(
        margin,
        margin,
        column_width,
        column_height,
        leftPadding=0,
        rightPadding=6,
        topPadding=0,
        bottomPadding=0,
        id='left_column',
    )
    right_frame = Frame(
        margin + column_width + gutter,
        margin,
        column_width,
        column_height,
        leftPadding=6,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id='right_column',
    )

    tier_colors = {
        'HOT LEAD': (0.80, 0.15, 0.15),
        'WARM LEAD': (0.85, 0.55, 0.05),
        'COLD LEAD': (0.20, 0.40, 0.75),
    }
    tier_color = tier_colors.get(tier, (0.2, 0.2, 0.2))

    def draw_header(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica-Bold', 16)
        canvas.drawString(margin, page_height - margin, 'Custom Headwear Client Qualification Form')
        canvas.setFont('Helvetica', 9)
        canvas.drawString(margin, page_height - margin - 16, datetime.now().strftime('Submitted %B %d, %Y at %I:%M %p'))

        canvas.setFillColorRGB(*tier_color)
        canvas.setFont('Helvetica-Bold', 14)
        canvas.drawString(margin, page_height - margin - 38, f'Lead Score: {score}/100 \u2014 {tier}')
        canvas.setFillColorRGB(0, 0, 0)

        canvas.line(margin, page_height - margin - 50, page_width - margin, page_height - margin - 50)
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id='two_column_answers', frames=[left_frame, right_frame], onPage=draw_header)])

    styles = getSampleStyleSheet()
    story = []

    for answer in answers:
        story.append(Paragraph(f'<b>{answer.label}</b>', styles['Heading4']))
        clean_value = answer.value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        story.append(Paragraph(clean_value.replace('\n', '<br/>'), styles['BodyText']))
        story.append(Spacer(1, 9))

    doc.build(story)
    return buffer.getvalue()


def get_business_name(answers: List[SurveyAnswer]) -> str:
    for answer in answers:
        if answer.label.lower() == 'business / brand name':
            return ' '.join(answer.value.split())
    return ''


def send_email(answers: List[SurveyAnswer]) -> None:
    if not SURVEY_SMTP_USER or not SURVEY_SMTP_APP_PASSWORD:
        raise HTTPException(
            status_code=500,
            detail='Survey email is not configured. Add SURVEY_SMTP_USER and SURVEY_SMTP_APP_PASSWORD to .env.',
        )

    score, tier, breakdown = score_lead(answers)
    pdf_bytes = build_pdf(answers, score, tier)
    summary = '\n'.join(f'{answer.label}: {answer.value}' for answer in answers)
    tier_emoji = {'HOT LEAD': '\U0001F525', 'WARM LEAD': '\u2600\uFE0F', 'COLD LEAD': '\u2744\uFE0F'}.get(tier, '')

    message = EmailMessage()
    business_name = get_business_name(answers)
    subject_prefix = f'{tier_emoji} {tier} ({score}/100)'
    message['Subject'] = (
        f'{subject_prefix}: {business_name}' if business_name else f'{subject_prefix} - Custom Headwear Survey'
    )
    message['From'] = SURVEY_SMTP_USER
    message['To'] = SURVEY_TO_EMAIL
    message.set_content(
        'A new custom headwear survey has been submitted.\n\n'
        f'LEAD SCORE: {score}/100 ({tier})\n'
        + ('\n'.join(f'  - {reason}' for reason in breakdown) if breakdown else '  (no scoring signals found)')
        + f'\n\n{summary}\n\n'
        'A PDF copy is attached.'
    )
    message.add_attachment(
        pdf_bytes,
        maintype='application',
        subtype='pdf',
        filename='custom-headwear-survey.pdf',
    )

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=20) as smtp:
            smtp.login(SURVEY_SMTP_USER, SURVEY_SMTP_APP_PASSWORD)
            smtp.send_message(message)
    except smtplib.SMTPException as exc:
        raise HTTPException(status_code=502, detail='Survey email could not be sent.') from exc


BASE_DIR = Path(__file__).parent


@app.get('/health')
def health_check():
    return {'status': 'ok'}


@app.post('/survey-submit')
def submit_survey(submission: SurveySubmission):
    answers = [
        SurveyAnswer(label=answer.label.strip(), value=answer.value.strip())
        for answer in submission.answers
        if answer.label.strip() and answer.value.strip()
    ]

    if not answers:
        raise HTTPException(status_code=400, detail='Survey submission must include answers.')

    send_email(answers)
    return {'status': 'sent'}

app.mount('/assets', StaticFiles(directory=BASE_DIR / 'Wear The Best _ Richardson_files'), name='assets')
app.mount(
    '/Wear The Best _ Richardson_files',
    StaticFiles(directory=BASE_DIR / 'Wear The Best _ Richardson_files'),
    name='assets_legacy',
)


@app.get('/')
def serve_index():
    return FileResponse(BASE_DIR / 'index.html')
