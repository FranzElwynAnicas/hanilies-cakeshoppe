import json
import re
import random
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib import error, request
from collections import defaultdict

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.urls import reverse

from .forms import (
    CAKE_DAILY_ORDER_LIMIT,
    PACKAGE_DAILY_EVENT_LIMIT,
    get_booking_date_availability,
)
from .models import Cake, Package, CakeOrder, PackageOrder


# ============================================
# CONSTANTS - MUST BE EXPORTED
# ============================================

HANILIES_AI_GREETING = (
    "Hello! I'm Hanilies AI, your virtual cake and event shopping assistant. "
    "Tell me your occasion, preferred date, budget, number of guests, or cake preferences, "
    "and I'll help you find available options."
)


# ============================================
# INTELLIGENT INTENT DETECTION
# ============================================

class IntentDetector:
    """Advanced intent detection with context awareness"""
    
    def __init__(self):
        self.intent_patterns = {
            'greeting': [
                r'^(hi|hello|hey|howdy|good morning|good afternoon|good evening|sup|yo)$',
                r'^(hi|hello|hey|howdy)[\s\!\.]+(there|everyone|team)',
                r'^(hey|hi|hello) there',
            ],
            'package_query': [
                r'(show|tell|display|list|view|get|find|see|give).*(me|us|the|your)?\s*(package|packages|event|events|booking|bookings)',
                r'(package|packages|event|events|booking|bookings).*(offer|have|available|do you have|got|provide|show|see|view)',
                r'^(packages|events|bookings)$',
                r'^package$',
                r'^event$',
                r'your packages',
                r'the packages',
                r'packages you have',
                r'packages available',
                r'what packages',
                r'which packages',
                r'do you have packages',
                r'got any packages',
                r'show me(?: the)? packages?',
                r'(best|top|popular|favorite).*(package|packages|event|events)',
                r'(wedding|christening|birthday|anniversary|party|corporate|kids|adult).*(package|packages)',
                r'event packages',
                r'package offerings',
                r'packages you offer',
                r'best selling packages',
                r'popular packages',
            ],
            'cake_query': [
                r'(show|tell|display|list|view|get|find|see|give).*(me|us|the|your)?\s*(cake|cakes|flavor|flavors)',
                r'(cake|cakes|flavor|flavors|bake|bakes).*(offer|have|available|do you have|got|provide|show|see|view)',
                r'^(cake|cakes|flavors|flavor)$',
                r'^cake$',
                r'your cakes',
                r'the cakes',
                r'cakes you have',
                r'what cakes',
                r'which cakes',
                r'show me(?: the)? cakes?',
                r'(best|top|popular|favorite).*(cake|cakes|flavor)',
                r'(chocolate|vanilla|ube|red velvet|strawberry|mocha).*(cake|cakes)',
            ],
            'count_query': [
                r'(how many|count|total|number of).*(cake|cakes|package|packages|order|orders|available)',
                r'(how many|count|total|number of).*(do you have|are there|available)',
                r'^(count|total|how many)$',
                r'how many cakes',
                r'how many packages',
                r'how many orders',
                r'total cakes',
                r'total packages',
            ],
            'price_query': [
                r'(how much|price|cost|budget|cheapest|expensive|affordable).*(cake|cakes|package|packages)',
                r'(under|below|within|around|about)\s*[0-9,]+',
                r'how much (is|are)',
                r'what(?: is| are) the price',
                r'price of',
                r'cost of',
            ],
            'customization_query': [
                r'(customize|customization|custom|customizable|personalize|personalized).*(cake|cakes|package|packages)',
                r'(can i|is it possible to|do you).*(customize|custom|personalize)',
                r'can I customize',
                r'custom cakes',
                r'custom packages',
                r'personalized cake',
                r'make my own',
                r'design my own',
            ],
            'delivery_query': [
                r'(delivery|deliver|delivered|shipping|ship|pickup|pick up).*(cake|cakes|package|packages)',
                r'(do you deliver|can you deliver|is delivery available)',
                r'how far in advance',
                r'lead time',
                r'advance order',
                r'when should I order',
                r'order in advance',
                r'how early',
                r'notice period',
                r'how much notice',
                r'preparation time',
                r'how long does it take',
                r'order ahead',
                r'book in advance',
            ],
            'date_query': [
                r'\d{4}-\d{2}-\d{2}',
                r'(when|date|available|book|schedule).*(need|want|looking for)',
                r'is.*available',
                r'what dates',
                r'date availability',
                r'check availability',
            ],
            'best_seller_query': [
                r'(best|top|popular|favorite|most).*(selling|seller|ordered|booked|requested)',
                r'(best|top|popular|favorite|most).*(cake|cakes|package|packages)',
                r'^(best sellers|top sellers|popular|favorites)$',
                r'best selling',
                r'most popular',
                r'customer favorite',
                r'best selling packages',
                r'popular packages',
            ],
            'menu_query': [
                r'(menu|selection|choices|options|offerings|catalog|collection).*(cake|cakes|package|packages|have|available)',
                r'^(menu|options|choices|offerings|catalog|collection)$',
                r'what do you have',
                r'what is available',
                r'what are your options',
            ],
            'about_query': [
                r'(about|info|information|tell me about|what is|what are).*(hanilies|shop|store|business|company)',
                r'(who are you|what is this|about hanilies)',
                r'about the shop',
            ],
            'contact_query': [
                r'(contact|reach|message|email|phone|call).*(you|hanilies|shop|store)',
                r'(how can i|how do i).*(contact|reach|message)',
                r'contact number',
                r'email address',
                r'where are you located',
            ],
            'status_query': [
                r'(status|update|progress|where is).*(order|booking|delivery)',
                r'(check|track|view).*(order|booking|delivery|status)',
                r'order status',
                r'track order',
                r'my order',
            ],
            'help_query': [
                r'^(help|help me|assist|guide|what can you do|how to use)',
                r'(what can you|how do you|help with)',
                r'how does this work',
                r'how to use',
            ],
            'thanks_query': [
                r'^(thank|thanks|appreciate|ty|thank you|thx|thank you so much)',
                r'thanks!',
                r'appreciate it',
            ],
        }
        
        # Context tracking for follow-up responses
        self.context = {
            'last_intent': None,
            'last_query': None,
            'mentioned_cakes': [],
            'mentioned_packages': [],
        }
    
    def detect_intent(self, message, previous_intent=None):
        """Detect the primary intent of the message with context awareness"""
        message_lower = message.lower().strip()
        
        # First check for common package variations
        package_variations = [
            r'^packages?$',
            r'^events?$',
            r'^bookings?$',
            r'^your packages$',
            r'^the packages$',
            r'^show me packages$',
            r'^show me your packages$',
            r'^show me the packages$',
            r'^packages you offer$',
            r'^packages available$',
            r'^best selling packages$',
            r'^popular packages$',
        ]
        for pattern in package_variations:
            if re.match(pattern, message_lower, re.IGNORECASE):
                return 'package_query'
        
        # Check for pure cake variations
        cake_variations = [
            r'^cakes?$',
            r'^flavors?$',
            r'^your cakes$',
            r'^the cakes$',
            r'^show me cakes$',
            r'^show me your cakes$',
            r'^show me the cakes$',
            r'^cakes you have$',
            r'^cakes available$',
        ]
        for pattern in cake_variations:
            if re.match(pattern, message_lower, re.IGNORECASE):
                return 'cake_query'
        
        # Check if this is a follow-up to a previous question
        if previous_intent and len(message.split()) < 4:
            followup_affirmatives = ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'show', 'tell', 'display', 'list', 'more', 'please']
            if previous_intent in ['package_query', 'cake_query', 'best_seller_query'] and any(word in message_lower for word in followup_affirmatives):
                return previous_intent
        
        # Check each intent pattern
        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, message_lower, re.IGNORECASE):
                    return intent
        
        # If no pattern matches but it contains package/cake keywords
        if 'package' in message_lower or 'event' in message_lower:
            return 'package_query'
        if 'cake' in message_lower or 'flavor' in message_lower:
            return 'cake_query'
        
        return 'general'


# ============================================
# CONVERSATION MANAGER
# ============================================

class ConversationManager:
    """Manages conversation state and context"""
    
    def __init__(self):
        self.session = defaultdict(dict)
    
    def get_or_create_session(self, session_id='default'):
        if session_id not in self.session:
            self.session[session_id] = {
                'intent': None,
                'last_message': None,
                'mentioned_items': [],
                'conversation_history': [],
            }
        return self.session[session_id]
    
    def update_context(self, session_id, message, intent, products=None):
        session = self.get_or_create_session(session_id)
        session['intent'] = intent
        session['last_message'] = message
        if products:
            session['mentioned_items'] = products
        session['conversation_history'].append({
            'message': message,
            'intent': intent,
            'timestamp': datetime.now().isoformat()
        })
        # Keep history manageable
        if len(session['conversation_history']) > 20:
            session['conversation_history'] = session['conversation_history'][-10:]
        return session


# Initialize the intent detector and conversation manager
intent_detector = IntentDetector()
conversation_manager = ConversationManager()


# ============================================
# SMART RESPONSE GENERATOR
# ============================================

class SmartResponseGenerator:
    """Generates intelligent, context-aware responses"""
    
    def __init__(self):
        self.greetings = [
            "Hello! 👋 How can I help you with cakes or event packages today?",
            "Hi there! 🎂 Welcome to Hanilies Cakeshoppe! What can I assist you with?",
            "Hey! 😊 I'm here to help you find the perfect cake or event package!",
            "Good to see you! 💕 What are you looking for today - a cake, a package, or something else?",
            "Hello! ✨ Ready to help you plan your celebration. What do you need?",
        ]
        
        self.thanks_responses = [
            "You're welcome! 😊 Is there anything else I can help with?",
            "Happy to help! 🎂 Let me know if you need anything else.",
            "My pleasure! 💕 Feel free to ask if you have more questions.",
            "Anytime! ✨ I'm here whenever you need me.",
        ]
        
        self.help_responses = [
            "I can help you with:\n• Finding cakes by flavor, theme, or budget\n• Exploring event packages\n• Checking availability and pricing\n• Customization options\n• Order tracking and status\n• General questions about Hanilies Cakeshoppe\n\nJust ask me anything! 🎂",
            "Here's what I can do:\n🍰 Find the perfect cake\n🎁 Explore event packages\n💰 Check prices and budgets\n📅 Check date availability\n🎨 Customize your order\n📦 Track your order\n\nWhat would you like to know?",
        ]
        
        self.no_results = [
            "I couldn't find any {items} matching your request. We have {total} {items} available. Try being more specific about what you're looking for! 🎁",
            "Hmm, I don't have any {items} for that. Can you tell me more about what you're looking for? I'd love to help! 💕",
            "No {items} found matching that description. We have {total} {items} available - want to see them all? 🎂",
            "I searched but couldn't find {items} matching that. What else are you looking for? I can help narrow it down!",
        ]
    
    def generate(self, intent, message, context):
        """Generate a smart response based on intent and context"""
        
        # Handle different intents
        if intent == 'greeting':
            return random.choice(self.greetings)
        
        if intent == 'thanks_query':
            return random.choice(self.thanks_responses)
        
        if intent == 'help_query':
            return random.choice(self.help_responses)
        
        if intent == 'count_query':
            return self._handle_count_query(message, context)
        
        if intent == 'package_query':
            return self._handle_package_query(message, context)
        
        if intent == 'cake_query':
            return self._handle_cake_query(message, context)
        
        if intent == 'best_seller_query':
            return self._handle_best_seller_query(message, context)
        
        if intent == 'price_query':
            return self._handle_price_query(message, context)
        
        if intent == 'customization_query':
            return self._handle_customization_query(message, context)
        
        if intent == 'delivery_query':
            return self._handle_delivery_query(message, context)
        
        if intent == 'date_query':
            return self._handle_date_query(message, context)
        
        if intent == 'menu_query':
            return self._handle_menu_query(message, context)
        
        if intent == 'about_query':
            return self._handle_about_query(message, context)
        
        if intent == 'contact_query':
            return self._handle_contact_query(message, context)
        
        if intent == 'status_query':
            return self._handle_status_query(message, context)
        
        # General fallback
        return self._handle_general_query(message, context)
    
    def _handle_count_query(self, message, context):
        """Handle count queries intelligently"""
        message_lower = message.lower()
        
        # Count cakes
        if 'cake' in message_lower or 'cakes' in message_lower:
            total_cakes = Cake.objects.filter(is_active=True, is_archived=False).count()
            if total_cakes == 0:
                return "We don't have any cakes right now, but we're always baking new ones! 🎂"
            return f"We currently have {total_cakes} delicious cakes available! Would you like me to show you some?"
        
        # Count packages
        if 'package' in message_lower or 'packages' in message_lower:
            total_packages = Package.objects.filter(status='active', is_archived=False).count()
            if total_packages == 0:
                return "We don't have any packages right now, but we're adding new ones regularly! 🎁"
            return f"We offer {total_packages} amazing event packages! Would you like to see them?"
        
        # Count orders
        if 'order' in message_lower or 'orders' in message_lower:
            total_orders = CakeOrder.objects.count() + PackageOrder.objects.count()
            return f"We've proudly served {total_orders} happy customers! 🎉"
        
        # General count
        total_cakes = Cake.objects.filter(is_active=True, is_archived=False).count()
        total_packages = Package.objects.filter(status='active', is_archived=False).count()
        return f"We have {total_cakes} cakes and {total_packages} packages available. What would you like to explore?"
    
    def _handle_package_query(self, message, context):
        """Handle package queries - show all active packages with better formatting"""
        # Parse budget if mentioned
        budget = self._extract_budget(message)
        
        # Get all active packages
        packages = Package.objects.filter(
            status='active',
            is_archived=False
        ).annotate(
            order_count=Count('orders')
        ).order_by('-order_count', 'base_price', 'name')
        
        # Only apply budget filter if specified
        if budget:
            packages = packages.filter(base_price__lte=budget)
        
        # Try to detect event type from message
        event_type = None
        event_types = ['wedding', 'christening', 'birthday', 'anniversary', 'kids', 'adult', 'party']
        for et in event_types:
            if et in message.lower():
                event_type = et
                break
        
        # If they mentioned an event type, try to filter
        if event_type:
            type_mapping = {
                'wedding': 'wedding',
                'christening': 'christening',
                'birthday': 'kids_birthday',
                'kids': 'kids_birthday',
                'adult': 'adults_party',
                'party': 'adults_party',
            }
            mapped_type = type_mapping.get(event_type, event_type)
            
            filtered = packages.filter(package_type__icontains=mapped_type)
            if filtered.exists():
                packages = filtered
        
        # Get packages to show (limit to 5)
        packages_list = list(packages[:5])
        total_packages = Package.objects.filter(status='active', is_archived=False).count()
        
        if not packages_list:
            all_packages = Package.objects.filter(
                status='active', is_archived=False
            ).order_by('name')[:5]
            
            if all_packages.exists():
                packages_list = list(all_packages)
                note = f"\n\n💡 I couldn't find specific '{event_type}' packages, but here are all our available packages:"
            else:
                return f"We have {total_packages} packages in our system, but none are currently active. Please check back later! 🎁"
        else:
            note = ""
        
        # Build response with better formatting
        if event_type and packages_list:
            response = f"✨ I found these {event_type} packages for you:\n\n"
        else:
            response = f"✨ Here are our available packages:\n\n"
        
        for pkg in packages_list:
            description = pkg.description or ''
            first_sentence = description.split('.')[0][:80] if description else ''
            
            response += f"🎁 **{pkg.name}** — ₱{pkg.base_price}\n"
            response += f"   📋 {pkg.get_package_type_display()}\n"
            if first_sentence:
                response += f"   📝 {first_sentence}...\n"
            if pkg.order_count:
                response += f"   📦 {pkg.order_count} bookings\n"
            response += "\n"
        
        if note:
            response += note + "\n"
        
        response += "Which one catches your eye? I can tell you more about what's included! 💕"
        return response
    
    def _handle_cake_query(self, message, context):
        """Handle cake queries - show all active cakes with better formatting"""
        # Parse budget if mentioned
        budget = self._extract_budget(message)
        
        # Get all active cakes
        cakes = Cake.objects.filter(
            is_active=True, is_archived=False
        ).annotate(
            order_count=Count('orders')
        ).order_by('-order_count', 'price', 'name')
        
        # Only apply budget filter if specified
        if budget:
            cakes = cakes.filter(price__lte=budget)
        
        # Try to detect flavor from message
        flavors = ['chocolate', 'vanilla', 'ube', 'red velvet', 'strawberry', 'mocha', 'mango', 'caramel']
        detected_flavor = None
        for flavor in flavors:
            if flavor in message.lower():
                detected_flavor = flavor
                break
        
        # Try to detect theme/occasion
        themes = ['birthday', 'wedding', 'christening', 'anniversary', 'custom']
        detected_theme = None
        for theme in themes:
            if theme in message.lower():
                detected_theme = theme
                break
        
        # Apply filters only if detected
        if detected_theme:
            cakes = cakes.filter(category=detected_theme)
        
        if detected_flavor:
            cakes = cakes.filter(
                Q(name__icontains=detected_flavor) | 
                Q(description__icontains=detected_flavor)
            )
        
        # Get top 5 cakes to show
        cakes_list = list(cakes[:5])
        total_cakes = Cake.objects.filter(is_active=True, is_archived=False).count()
        
        if not cakes_list:
            # If no cakes found, show all cakes with a note
            all_cakes = Cake.objects.filter(
                is_active=True, is_archived=False
            ).order_by('name')[:5]
            
            if all_cakes.exists():
                cakes_list = list(all_cakes)
                note = f"\n\n💡 I couldn't find specific '{detected_flavor or detected_theme or ''}' cakes, but here are all our cakes:"
            else:
                return f"We have {total_cakes} cakes available, but none are active right now. Please check back later! 🎂"
        else:
            note = ""
        
        # Build response with better formatting
        if detected_flavor:
            response = f"✨ I found these {detected_flavor} cakes for you:\n\n"
        elif detected_theme:
            response = f"✨ I found these {detected_theme} cakes for you:\n\n"
        else:
            response = f"✨ Here are our available cakes:\n\n"
        
        for cake in cakes_list:
            description = cake.description or ''
            first_sentence = description.split('.')[0][:80] if description else ''
            
            response += f"🎂 **{cake.name}** — ₱{cake.price}\n"
            response += f"   📋 {cake.get_category_display()}\n"
            if first_sentence:
                response += f"   📝 {first_sentence}...\n"
            if cake.order_count:
                response += f"   📊 {cake.order_count} orders\n"
            response += "\n"
        
        if note:
            response += note + "\n"
        
        response += "Which one speaks to you? I'd love to tell you more about it! 💕"
        return response
    
    def _handle_best_seller_query(self, message, context):
        """Handle best seller queries - show top packages or cakes with better formatting"""
        # Check if asking about packages specifically
        if 'package' in message.lower() or 'event' in message.lower():
            packages = Package.objects.filter(
                status='active', is_archived=False
            ).annotate(
                order_count=Count('orders')
            ).filter(order_count__gt=0).order_by('-order_count')[:3]
            
            if not packages:
                # Show all packages with a note
                packages = Package.objects.filter(
                    status='active', is_archived=False
                ).order_by('name')[:3]
                note = "We don't have enough order data yet, but here are our available packages:"
            else:
                note = "These are our most popular packages based on bookings:"
            
            response = f"🏆 {note}\n\n"
            for pkg in packages:
                description = pkg.description or ''
                first_sentence = description.split('.')[0][:80] if description else ''
                
                response += f"🎁 **{pkg.name}** — ₱{pkg.base_price}\n"
                response += f"   📋 {pkg.get_package_type_display()}\n"
                if first_sentence:
                    response += f"   📝 {first_sentence}...\n"
                if pkg.order_count:
                    response += f"   📦 {pkg.order_count} bookings\n"
                response += "\n"
            response += "Would you like more details on any of them?"
            return response
        
        # Default to cakes
        cakes = Cake.objects.filter(
            is_active=True, is_archived=False
        ).annotate(
            order_count=Count('orders')
        ).filter(order_count__gt=0).order_by('-order_count')[:3]
        
        if not cakes:
            cakes = Cake.objects.filter(
                is_active=True, is_archived=False
            ).order_by('name')[:3]
            note = "We don't have enough order data yet, but here are our available cakes:"
        else:
            note = "These are our most popular cakes based on orders:"
        
        response = f"🏆 {note}\n\n"
        for cake in cakes:
            description = cake.description or ''
            first_sentence = description.split('.')[0][:80] if description else ''
            
            response += f"🎂 **{cake.name}** — ₱{cake.price}\n"
            response += f"   📋 {cake.get_category_display()}\n"
            if first_sentence:
                response += f"   📝 {first_sentence}...\n"
            if cake.order_count:
                response += f"   📊 {cake.order_count} orders\n"
            response += "\n"
        response += "Would you like to see one of them?"
        return response
    
    def _handle_price_query(self, message, context):
        """Handle price queries"""
        budget = self._extract_budget(message)
        
        if not budget:
            return "I'm not sure what budget you're looking for. Can you tell me how much you want to spend? (e.g., ₱1000, under 2000, around 5000)"
        
        cakes = Cake.objects.filter(
            is_active=True, is_archived=False,
            price__lte=budget
        ).order_by('price')[:3]
        
        packages = Package.objects.filter(
            status='active', is_archived=False,
            base_price__lte=budget
        ).order_by('base_price')[:2]
        
        response = f"✨ With a budget of ₱{budget}, here's what's available:\n\n"
        
        if cakes:
            response += "🍰 **Cakes:**\n"
            for cake in cakes:
                description = cake.description or ''
                first_sentence = description.split('.')[0][:60] if description else ''
                response += f"   • **{cake.name}** — ₱{cake.price}\n"
                if first_sentence:
                    response += f"     {first_sentence}...\n"
        else:
            response += "🍰 No cakes in this budget range.\n"
        
        if packages:
            response += "\n🎁 **Packages:**\n"
            for pkg in packages:
                description = pkg.description or ''
                first_sentence = description.split('.')[0][:60] if description else ''
                response += f"   • **{pkg.name}** — ₱{pkg.base_price}\n"
                if first_sentence:
                    response += f"     {first_sentence}...\n"
        else:
            response += "\n🎁 No packages in this budget range.\n"
        
        response += "\nWould you like to see more options? 💕"
        return response
    
    def _handle_customization_query(self, message, context):
        """Handle customization queries"""
        return """✨ Yes, you can customize your cakes and packages! 🎨

**For Cakes:**
• Choose your flavor, filling, and frosting
• Pick the size and number of tiers
• Select colors and themes
• Add personal messages and decorations
• Upload a design reference

**For Packages:**
• Customize the cake included
• Add extra items like cupcakes or balloons
• Choose the event setup style
• Select your preferred decorations

Just start your order and you'll see all customization options! Would you like to begin? ✨"""
    
    def _handle_delivery_query(self, message, context):
        """Handle delivery and lead time queries"""
        return """📦 **Order Lead Time & Delivery Information**

**How far in advance should you order?**
• Orders must be placed at least **3 days** before your event
• You can book up to **30 days** in advance
• This gives us time to prepare your perfect cake!

**Delivery Details:**
• Delivery is available within our service areas
• Delivery date is confirmed after payment verification
• You can choose pickup or delivery during checkout

**Service Areas:**
Oroquieta City and surrounding municipalities

Would you like to check availability for a specific date? 🚗"""
    
    def _handle_date_query(self, message, context):
        """Handle date availability queries"""
        # Extract date if mentioned
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', message)
        if date_match:
            date_str = date_match.group(1)
            try:
                check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                from .forms import get_booking_date_availability
                availability = get_booking_date_availability(check_date, 'all')
                if availability['available']:
                    return f"📅 {date_str} is available! Would you like to book something? 🎂"
                else:
                    return f"📅 {date_str} is not available. {availability['message']} Would you like to check another date?"
            except:
                pass
        
        return "I can check date availability for you! Just tell me a date in YYYY-MM-DD format, or ask about our booking window. 📅"
    
    def _handle_menu_query(self, message, context):
        """Handle menu/offerings queries"""
        total_cakes = Cake.objects.filter(is_active=True, is_archived=False).count()
        total_packages = Package.objects.filter(status='active', is_archived=False).count()
        
        cake_categories = Cake.objects.filter(is_active=True, is_archived=False).values_list('category', flat=True).distinct()
        package_types = Package.objects.filter(status='active', is_archived=False).values_list('package_type', flat=True).distinct()
        
        response = f"🎂 **Hanilies Cakeshoppe Menu**\n\n"
        response += f"**Cakes:** {total_cakes} available\n"
        if cake_categories:
            response += f"   Categories: {', '.join(dict(Cake.CAKE_CATEGORIES).get(c, c) for c in cake_categories)}\n"
        response += "\n"
        response += f"**Packages:** {total_packages} available\n"
        if package_types:
            response += f"   Types: {', '.join(dict(Package.PACKAGE_TYPES).get(p, p) for p in package_types)}\n"
        response += "\nWould you like to see specific categories? 🎁"
        return response
    
    def _handle_about_query(self, message, context):
        """Handle about queries"""
        return """🏠 **About Hanilies Cakeshoppe**

Founded in 2009 by Ms. Teresa T. Rabillas, Hanilies Cakeshoppe began as a passion for baking family celebration cakes.

What started as a small home-based business has grown into an established enterprise with ten dedicated employees, handling a high volume of orders, particularly for first birthdays and during the peak season of December.

Today, we continue to serve our community with the same love and dedication that started it all, now enhanced with modern technology to serve you better.

**Our Mission:** To create sweet and memorable moments for our customers through high-quality, beautifully crafted cakes and exceptional service.

**Our Vision:** To be the most trusted and preferred cake shop in the community.

Would you like to know more about our cakes or packages? 🎂"""
    
    def _handle_contact_query(self, message, context):
        """Handle contact queries"""
        return """📞 **Contact Hanilies Cakeshoppe**

📍 **Location:**
FRM4+623, Independence St
Oroquieta City, 7207
Misamis Occidental

📱 **Phone:** 09275294221

📧 **Email:** cakeshoppehanilies@gmail.com

🕐 **Business Hours:**
Monday - Friday: 8:00 AM - 8:00 PM
Saturday: 9:00 AM - 6:00 PM
Sunday: 9:00 AM - 5:00 PM
Holidays: 10:00 AM - 4:00 PM

You can also use our Contact page to send a message! 💌"""
    
    def _handle_status_query(self, message, context):
        """Handle order status queries"""
        return """🔍 **Order Tracking**

You can track your orders in two ways:

1. **On our website:** Visit the "Track Order" page in your account
2. **Contact us directly:** We can check your order status

To track an order, you'll need:
• Your order number
• The email address used for the order

If you have an account, just log in and go to "Track Order"! 📦"""
    
    def _handle_general_query(self, message, context):
        """Handle general queries"""
        # Check if it's a simple yes/no
        if message.lower() in ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay']:
            previous_intent = context.get('intent')
            if previous_intent == 'package_query':
                return "Great! Would you like me to show you our packages or would you prefer to start with a specific event type? 🎁"
            elif previous_intent == 'cake_query':
                return "Awesome! Should I show you our cakes by flavor, category, or budget? 🎂"
            return "What would you like to explore? I can help with cakes, packages, pricing, or anything else! ✨"
        
        # Check for "no" responses
        if message.lower() in ['no', 'nope', 'nah', 'not really']:
            return "No problem! Just let me know what you're looking for and I'll help you find it. 🎂"
        
        # Generic help
        return """I'm here to help! Here's what you can ask me:

🍰 **Cakes:** "Show me chocolate cakes" or "What cakes do you have?"
🎁 **Packages:** "Show me event packages" or "What packages do you offer?"
💰 **Pricing:** "Cakes under ₱1000" or "How much are packages?"
📅 **Dates:** "Is 2024-12-25 available?" or "When should I order?"
🎨 **Customization:** "Can I customize a cake?" or "How to customize?"

Just ask and I'll help! What would you like to know? 💕"""
    
    def _extract_budget(self, message):
        """Extract budget from message"""
        patterns = [
            r'(?:budget|around|under|below|within|for|about)\s*(?:of\s*)?(?:php|peso|pesos|p|₱)?\s*([0-9,]+(?:\.[0-9]{1,2})?)',
            r'(?:php|peso|pesos|p|₱)\s*([0-9,]+(?:\.[0-9]{1,2})?)',
            r'([0-9,]+(?:\.[0-9]{1,2})?)\s*(?:php|peso|pesos)',
            r'under\s*([0-9,]+)',
            r'below\s*([0-9,]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1).replace(',', ''))
                except:
                    return None
        return None


# ============================================
# MAIN AI ASSISTANT
# ============================================

def get_hanilies_ai_reply(message, session_id='default'):
    """
    Main entry point for the AI assistant.
    Returns a smart, context-aware response.
    """
    message = (message or '').strip()
    if not message:
        return {
            'reply': "Hi! What can I help you with today? 🎂",
            'used_external_ai': False,
            'suggestions': {'cakes': [], 'packages': [], 'booking': None}
        }
    
    # Get session context
    session = conversation_manager.get_or_create_session(session_id)
    previous_intent = session.get('intent')
    
    # Detect intent
    intent = intent_detector.detect_intent(message, previous_intent)
    
    # Build context for response
    context = {
        'intent': intent,
        'previous_intent': previous_intent,
        'message': message,
        'session': session,
    }
    
    # Generate response
    generator = SmartResponseGenerator()
    reply = generator.generate(intent, message, context)
    
    # Update session
    conversation_manager.update_context(session_id, message, intent)
    
    # ============================================
    # FIXED: Get suggestions based on the ACTUAL response
    # ============================================
    suggestions = {'cakes': [], 'packages': [], 'booking': None}
    message_lower = message.lower()
    
    # For cake queries
    if intent == 'cake_query':
        # Start with all active cakes
        cakes = Cake.objects.filter(
            is_active=True, is_archived=False
        ).order_by('name')
        
        # Filter by flavor if mentioned
        flavors = ['chocolate', 'vanilla', 'ube', 'red velvet', 'strawberry', 'mocha', 'mango', 'caramel']
        detected_flavor = None
        for flavor in flavors:
            if flavor in message_lower:
                detected_flavor = flavor
                break
        
        # Filter by category/theme if mentioned
        categories = {
            'wedding': 'wedding',
            'birthday': 'birthday',
            'christening': 'christening',
            'anniversary': 'anniversary',
            'custom': 'custom',
        }
        detected_category = None
        for key, value in categories.items():
            if key in message_lower:
                detected_category = value
                break
        
        # Apply filters
        if detected_category:
            cakes = cakes.filter(category=detected_category)
        
        if detected_flavor:
            cakes = cakes.filter(
                Q(name__icontains=detected_flavor) | 
                Q(description__icontains=detected_flavor)
            )
        
        # If no cakes found with filters, show all cakes
        if not cakes.exists():
            cakes = Cake.objects.filter(is_active=True, is_archived=False).order_by('name')
        
        # Limit to 3
        suggestions['cakes'] = [_cake_to_payload(cake) for cake in cakes[:3]]
    
    # For package queries
    elif intent == 'package_query' or intent == 'best_seller_query':
        # Start with all active packages
        packages = Package.objects.filter(
            status='active', is_archived=False
        ).order_by('name')
        
        # Filter by event type if mentioned
        if 'wedding' in message_lower:
            packages = packages.filter(package_type='wedding')
        elif 'christening' in message_lower:
            packages = packages.filter(package_type='christening')
        elif 'birthday' in message_lower or 'kids' in message_lower:
            packages = packages.filter(package_type='kids_birthday')
        elif 'adult' in message_lower:
            packages = packages.filter(package_type='adults_party')
        
        # For best selling, order by order_count
        if intent == 'best_seller_query':
            packages = packages.annotate(
                order_count=Count('orders')
            ).order_by('-order_count')
        
        # Limit to 3
        suggestions['packages'] = [_package_to_payload(pkg) for pkg in packages[:3]]
    
    elif intent == 'menu_query':
        cakes = Cake.objects.filter(
            is_active=True, is_archived=False
        ).order_by('name')[:3]
        packages = Package.objects.filter(
            status='active', is_archived=False
        ).order_by('name')[:2]
        suggestions['cakes'] = [_cake_to_payload(cake) for cake in cakes]
        suggestions['packages'] = [_package_to_payload(pkg) for pkg in packages]
    
    return {
        'reply': reply,
        'used_external_ai': False,
        'suggestions': suggestions,
    }


# ============================================
# HELPER FUNCTIONS
# ============================================

def _cake_to_payload(cake):
    return {
        'type': 'cake',
        'name': cake.name,
        'category': cake.get_category_display(),
        'category_key': cake.category,
        'price': str(cake.price),
        'stock': cake.stock,
        'description': cake.description or '',
        'image_url': cake.image_url(),
        'url': f"{reverse('cake_customize')}?cake_id={cake.id}",
        'id': cake.id,
    }


def _package_to_payload(package):
    return {
        'type': 'package',
        'name': package.name,
        'category': package.get_package_type_display(),
        'category_key': package.package_type,
        'price': str(package.base_price),
        'stock': package.stock,
        'description': package.description or '',
        'image_url': package.image.url if package.image else '/static/images/bg.png',
        'url': f"{reverse('order_package')}?package_id={package.id}",
        'id': package.id,
    }