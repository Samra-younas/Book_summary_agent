from flask import Flask, render_template, request, jsonify
import requests
from dotenv import load_dotenv
import os
import time
import re
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()
app = Flask(__name__)

# CHANGED: OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AI_MODEL = "gpt-4o-mini"  # or "gpt-4o" for better quality
API_URL = "https://api.openai.com/v1/chat/completions"
SCOPES = ["https://www.googleapis.com/auth/documents"]
# forbidden words
FORBIDDEN_WORDS = [
    'from the book lesson', 'In the first chapter', 'In this chapter',
    'key lesson', 'the book provides valuable', 'main point',
    'conclusion of this summary', 'this summary shows', 'The author',
    'Finally,', 'This chapter', 'Conclusion', 'In summary,', 'To summarize,',
    'In conclusion,', 'Overall,', 'To sum up,', 'In brief,', 'In essence,',
    'In short,', 'This section', 'This part', 'This passage', 'The chapter',
    'the section', 'the passage',
]

FORBIDDEN_PATTERNS = [
    r'\bembrac(e|ing|ed|es)\b', r'\bfoster(ing|ed|s)\b', r'\bEMBRACE-(ing|ed|s)\b',
    r'\bUNVEIL(ing|ed|s)\b', r'\bUNREVEAL(ing|ed|s)\b', r'\bNAVIGATE(ing|ed|s)\b',
    r'\bmaster(ing|ed|s)\b', r'\bTHRIVE(ing|ed|s)\b', r'\bUNLEASH(ing|ed|s)\b',
]

ING_STARTS = ['understanding', 'exploring', 'examining', 'analyzing', 'discovering',
              'learning', 'finding', 'revealing', 'showing', 'demonstrating',
              'presenting', 'introducing', 'discussing', 'uncovering', 'breaking down']

#Create Flask App route home page
@app.route('/')
def index():
    return render_template('index.html')

# rouet for create sumamry  
@app.route('/create-summary', methods=['POST'])
def create_summary():
    start_time = time.time()
    data = request.json
    book_name = data.get('book_name')
    author = data.get('author')
    initial_input_text = data.get('summary')
    
    if not all([book_name, author, initial_input_text]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Dynamically determine section count (10-13 based on content length)
    section_count = calculate_section_count(initial_input_text)
    sections = split_summary_into_sections(initial_input_text, section_count)
    section_summaries_list = []
    generated_summaries_full_text = []
    
    for idx, section in enumerate(sections, 1):
        section_result_text = create_section_summary(section, idx, section_count)
        if section_result_text.startswith(("Request Error:", "General Error:", "Error:")):
            return jsonify({'error': f"Failed: {section_result_text}"}), 500
        section_summaries_list.append({'content': section_result_text})
        generated_summaries_full_text.append(section_result_text)
    
    combined_summaries = "\n\n---\n\n".join(generated_summaries_full_text)
    
    final_super_summary = create_super_summary(combined_summaries)
    final_abstract = create_abstract(combined_summaries, book_name, author)
    final_key_points = create_key_points(combined_summaries)
    final_writer_profile = create_writer_profile(author)
    final_story = create_story(combined_summaries)
   
    
    doc_url = create_google_doc(book_name, author, {
        'super_summary': final_super_summary,
        'abstract': final_abstract,
        'key_points': final_key_points,
        'main_content': section_summaries_list,
        'writer_profile': final_writer_profile,
        'story': final_story
    })
    
    print(f"📌 DEBUG: Google Doc URL = {doc_url}")
    
    total_time = time.time() - start_time
    total_minutes = int(total_time // 60)
    total_seconds = int(total_time % 60)
    
    return jsonify({
        'status': 'success',
        'book_name': book_name,
        'author': author,
        'super_summary': final_super_summary,
        'abstract': final_abstract,
        'key_points': final_key_points,
        'main_content': section_summaries_list,
        'writer_profile': final_writer_profile,
        'story': final_story,
        'google_doc_url': doc_url,
        'total_time': f'{total_minutes}m {total_seconds}s'
    })
#Section division based on word  count on summary 
def calculate_section_count(text):
    """Determine optimal section count between 10-13 based on content length"""
    word_count = len(text.split())
    if word_count < 2000:
        return 10
    elif word_count < 4000:
        return 11
    elif word_count < 6000:
        return 12
    else:
        return 13

# Call Ai APi
def make_ai_call(prompt):
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,  # Optional: adjust creativity (0-2)
        "max_tokens": 2000   # Optional: adjust response length
    }
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'] if 'choices' in result else "Error: No content"
    except requests.exceptions.RequestException as e:
        return f"Request Error: {str(e)}"
    except Exception as e:
        return f"General Error: {str(e)}"
# Remove  vague
def clean_ai_response(text):
    """Remove common AI preambles and clean up response"""
    preambles = [
        r'^Here is (?:the |a )?.*?:\s*',
        r'^Here are (?:the |some )?.*?:\s*',
        r'^Here\'s (?:the |a )?.*?:\s*',
        r'^(?:The |A )?(?:following is|answer is).*?:\s*',
        r'^I(?:\'ve| have) (?:created|written|made).*?:\s*',
        r'^Below is.*?:\s*',
        r'^Sure[,!].*?:\s*',
    ]
    
    for pattern in preambles:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
    
    text = re.sub(r'^\*\*(.*?)\*\*\s*$', r'\1', text, flags=re.MULTILINE)
    
    return text.strip()

def remove_forbidden_words(text):
    """Remove forbidden words/phrases from text"""
    # Remove exact forbidden words from the text
    for word in FORBIDDEN_WORDS:
        text = re.sub(re.escape(word), '', text, flags=re.IGNORECASE)
    
    # Remove words matching the forbidden patterns (e.g., embrace, fostering, etc.)
    for pattern in FORBIDDEN_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    return text.strip() 

#spilt section based on topic  or paragraph
def split_summary_into_sections(summary, section_count=10):
    """Split summary into optimal sections (10-13) without losing important info"""
    paragraphs = [p.strip() for p in summary.split('\n') if p.strip()]
    
    if len(paragraphs) <= section_count:
        return paragraphs
    
    section_size = len(paragraphs) // section_count
    remainder = len(paragraphs) % section_count
    sections = []
    
    para_idx = 0
    for i in range(section_count):
        # Distribute remainder paragraphs evenly
        size = section_size + (1 if i < remainder else 0)
        section_text = ' '.join(paragraphs[para_idx:para_idx + size])
        sections.append(section_text)
        para_idx += size
    
    return sections

#add style for docs file
def add_text_with_style(req_list, idx, text, bold=False, blue=False, size=12, center=False, justify=False):
    """Helper to add formatted text with alignment options"""
    # Remove markdown asterisks first
    text = text.replace('**', '')
    text = text.replace('- ', '• ')  # Convert dashes to bullets
    
    req_list.append({'insertText': {'location': {'index': idx}, 'text': text}})
    end_idx = idx + len(text)
    
    color = {'red': 0, 'green': 0, 'blue': 1} if blue else {'red': 0, 'green': 0, 'blue': 0}
    req_list.append({
        'updateTextStyle': {
            'range': {'startIndex': idx, 'endIndex': end_idx - 1},
            'textStyle': {
                'bold': bold,
                'fontSize': {'magnitude': size, 'unit': 'PT'},
                'weightedFontFamily': {'fontFamily': 'Merriweather'},
                'foregroundColor': {'color': {'rgbColor': color}}
            },
            'fields': 'bold,fontSize,weightedFontFamily,foregroundColor'
        }
    })
    
    if justify:
        alignment = 'JUSTIFIED'
    elif center:
        alignment = 'CENTER'
    else:
        alignment = 'START'
    
    req_list.append({
        'updateParagraphStyle': {
            'range': {'startIndex': idx, 'endIndex': end_idx - 1},
            'paragraphStyle': {'alignment': alignment},
            'fields': 'alignment'
        }
    })
    
    return end_idx
    # Create docs file
def create_google_doc(book_name, author, data):
    try:
        service = authenticate_google()
        doc = service.documents().create(body={'title': f'{book_name} - Summary'}).execute()
        doc_id = doc['documentId']
        req_list = []
        idx = 1
        
        idx = add_text_with_style(req_list, idx, f"{book_name}\n", bold=True, blue=False, size=20, center=True)
        idx = add_text_with_style(req_list, idx, f"{author}\n\n", bold=False, blue=False, size=12, center=True)
        
        if data.get('super_summary'):
            idx = add_text_with_style(req_list, idx, "Super Summary:\n", bold=True, blue=False, size=12, justify=False)
            idx = add_text_with_style(req_list, idx, f"{data['super_summary']}\n\n", bold=False, blue=False, size=12, justify=True)
        
        if data.get('abstract'):
            idx = add_text_with_style(req_list, idx, "Abstract:\n", bold=True, blue=False, size=12, justify=False)
            idx = add_text_with_style(req_list, idx, f"{data['abstract']}\n\n", bold=False, blue=False, size=12, justify=True)
        
        if data.get('key_points'):
            idx = add_text_with_style(req_list, idx, "Key Points:\n", bold=True, blue=False, size=12, justify=False)
            idx = add_text_with_style(req_list, idx, f"{data['key_points']}\n\n", bold=False, blue=False, size=12, justify=False)
        
        if data.get('main_content'):
            idx = add_text_with_style(req_list, idx, "Summary:\n", bold=True, blue=False, size=12, justify=False)
            for section in data['main_content']:
                content = section['content']
                lines = content.split('\n', 1)
                if len(lines) == 2:
                    heading = lines[0] + '\n'
                    body = lines[1] + '\n\n'
                    idx = add_text_with_style(req_list, idx, heading, bold=True, blue=True, size=12, justify=False)
                    idx = add_text_with_style(req_list, idx, body, bold=False, blue=False, size=12, justify=True)
                else:
                    idx = add_text_with_style(req_list, idx, f"{content}\n\n", bold=False, blue=False, size=12, justify=True)
        
        if data.get('writer_profile'):
            idx = add_text_with_style(req_list, idx, "Writer's Profile:\n", bold=True, blue=False, size=12, justify=False)
            idx = add_text_with_style(req_list, idx, f"{data['writer_profile']}\n\n", bold=False, blue=False, size=12, justify=True)
        
        if data.get('story'):
            idx = add_text_with_style(req_list, idx, "Story:\n", bold=True, blue=False, size=12)
            idx = add_text_with_style(req_list, idx, f"{data['story']}\n", bold=False, blue=False, size=12)
        
        
        service.documents().batchUpdate(documentId=doc_id, body={'requests': req_list}).execute()
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        print(f"✅ Google Doc Created Successfully: {doc_url}")
        return doc_url
    except Exception as e:
        error_msg = f"Google Doc Error: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg
#sumamry section rules

def create_section_summary(section_text, section_num, total_sections):
    """Create section summary with key points, examples, and clear formatting"""
    prompt = f"""Create a clear, engaging section summary. Follow these guidelines:

SECTION: {section_num}/{total_sections}


1. HEADING (6-7 words, must be unique and specific):
   - Reflect the actual content of the section
   - Use straightforward, book-like language (not poetic or vivid)
   - Avoid: "Understanding," "Exploring," "Analyzing," "Discovering," "Learning," "Finding," "Revealing"
   - Avoid: "Chapter," "Section," "Text," "Part," "Passage," "Story," -ing words
   - Example: Instead of "Understanding Water Cycles," use "How Water Cycles Work" or "The Water Cycle Process"

2. SUMMARY (200 words):
   - Use simple, clear, everyday language
   - Avoid: "Chapter," "Section," "Text," "Part," "Passage," "Story," "This text"
   - Skip poetic language; keep it straightforward
   - Don't mention the author or use pronouns like "the author says"

3. EXAMPLES & KEY POINTS (Required if present in source):
   - Include 1-2 concrete examples found in the section if available
   - List key takeaways as bullet points only if they improve readability
   - Make examples specific and relatable, not generic

4. FORMATTING:
   - Heading on first line
   - Summary immediately after (no extra breaks)
   - Use clear, scannable structure
   - Google Docs-friendly (no markdown)
4. **Section**: {section_num}/{total_sections}
   - Section Text: {section_text}
"""

    response = make_ai_call(prompt)
    response = clean_ai_response(response)
    response = remove_forbidden_words(response)
    return response
#super summary rules
def create_super_summary(text):
    """Create exactly 43-word conclusion"""
    prompt = f"""Write a conclusion that is EXACTLY 43 words. Count each word carefully.

CRITICAL RULES:
Give me a "43-word conclusion" of this summary that should be the essence of the whole summary
NOTE: KEEP IT GENERAL, DON'T USE ANY NAMES
HUMANIZE IT, AND DON'T USE COMPOUND SENTENCES. DO NOT USE ING FORM AND KEEP SENTENCES.
it must be suspeciously engaging to make the reader want to read the full book.
Never use pronoun or writer name.
                                        
Text: {text}"""
    
    response = make_ai_call(prompt)
    response = clean_ai_response(response)
    response = remove_forbidden_words(response)
    return response
#abstract section prompt
def create_abstract(text, book_name, author):
    """Create abstract (120 words max)"""
    prompt = f"""Write an abstract of 120 words or fewer.

CRITICAL RULES:
nthesize exactly or fewer than 120 words in paragraph form, that is, an abstract of the above whole text, creatively. In a format like "In the Book name" 
by "Author's Name," then start the abstract. It should include the most important message that this book/text wants to convey. It should be really interesting and must aim to engage the reader.”
STRICT RULES:
1. Maximum 120 words (count carefully!) 
2. Focus on the core message of the book/text
3. Use straightforward, clear, and the easiest language
4. Output ONLY the abstract (no heading or extra text)
5. No pronouns (use nouns instead), No -ing words   6. No introduction or preamble      
7. start with "In  {book_name} by {author},"

Text: {text}"""
    
    response = make_ai_call(prompt)
    response = clean_ai_response(response)
    response = remove_forbidden_words(response)
    return response

#key points pormpt
def create_key_points(text):
    """Create EXACTLY 7 one-liner bullet points"""
    prompt = f"""Create EXACTLY 7 bullet points. STRICT RULES:

CRITICAL RULES:
Synthesize information into 7 one-liner bullet points from the above-given text, and remember the following points. 
1- Make sure that they capture the essence of the whole text
2- They should promote learning
3- Keep them concise and must not exceed more than 1 line 
4- Use the easiest form of English
NOTE: KEEP IT GENERAL, DON'T USE ANY NAMES”

EXACT FORMAT:
• First one-liner
• Second one-liner
• Third one-liner
• Fourth one-liner
• Fifth one-liner
• Sixth one-liner
• Seventh one-liner

Text: {text}"""
    
    response = make_ai_call(prompt)
    response = clean_ai_response(response)
    response = remove_forbidden_words(response)
    
    # Ensure each bullet is on its own line
    lines = response.split('\n')
    formatted_points = []
    for line in lines:
        line = line.strip()
        if line:  # Only process non-empty lines
            if not line.startswith('•'):
                line = '• ' + line
            formatted_points.append(line)
    
    # Return with proper line breaks
    response = '\n'.join(formatted_points)
    return response
#writer prfiel prompt
def create_writer_profile(author):
    """Create EXACTLY 50-word author profile"""
    prompt = f"""Write EXACTLY 50 words about {author}. STRICT RULES:

1. Exactly 50 words (count carefully!)
2. Focus on writing career and achievements
3. Informative and concise
4. Output ONLY the 50-word profile
5. No pronouns (use nouns instead), No -ing words
6. No introduction or preamble
CONNECTIVITY:
- This conclusion should summarize the journey shown in summaries
- It should tie back to the abstract's main message
- It should explain why these lessons matter
Author: {author}"""
    
    response = make_ai_call(prompt)
    response = clean_ai_response(response)
    response = remove_forbidden_words(response) 
    return response

#create story  rules
def create_story(text):
    prompt = f"""Create a 250-word story from the summary given above that is interesting, has an element of humor, and keeps the same main message as the summary.
      The story must also have an emotional touch to make it more engaging. Include a concrete and memorable cue that ties directly to the moral so readers remember it easily.
        End with a takeaway that connects back to the cue.”. Include: humor, emotion, concrete memorable cue, clear takeaway
         Make it engaging and relatable
        Never mention the author's name in the story.
        - NO "Here is..." or any introduction
         Double-check not more than 250 words.
Summary: {text}"""
    
    response = make_ai_call(prompt)
    response = clean_ai_response(response)
    response = remove_forbidden_words(response)
    return response
# ============================================
# RUN APP
# ============================================
if __name__ == '__main__':
    app.run(debug=True, port=5002)
