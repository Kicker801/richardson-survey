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


def build_pdf(answers: List[SurveyAnswer]) -> bytes:
    buffer = BytesIO()
    page_width, page_height = letter
    margin = 42
    gutter = 18
    title_height = 74
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

    def draw_header(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica-Bold', 16)
        canvas.drawString(margin, page_height - margin, 'Custom Headwear Client Qualification Form')
        canvas.setFont('Helvetica', 9)
        canvas.drawString(margin, page_height - margin - 16, datetime.now().strftime('Submitted %B %d, %Y at %I:%M %p'))
        canvas.line(margin, page_height - margin - 30, page_width - margin, page_height - margin - 30)
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

    pdf_bytes = build_pdf(answers)
    summary = '\n'.join(f'{answer.label}: {answer.value}' for answer in answers)

    message = EmailMessage()
    business_name = get_business_name(answers)
    message['Subject'] = f'Custom Headwear Survey: {business_name}' if business_name else 'Custom Headwear Survey Submission'
    message['From'] = SURVEY_SMTP_USER
    message['To'] = SURVEY_TO_EMAIL
    message.set_content(
        'A new custom headwear survey has been submitted.\n\n'
        f'{summary}\n\n'
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

app.mount('/assets', StaticFiles(directory=BASE_DIR / 'assets'), name='assets')


@app.get('/')
def serve_index():
    return FileResponse(BASE_DIR / 'index.html')
