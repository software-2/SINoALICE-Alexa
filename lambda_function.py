# -*- coding: utf-8 -*-

import os
import math
import logging
from datetime import datetime
from datetime import timedelta

import ask_sdk_core.utils as ask_utils
from ask_sdk_core.api_client import DefaultApiClient
from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.dispatch_components import AbstractExceptionHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.canfulfill import CanFulfillIntent, CanFulfillIntentValues
from ask_sdk_model.interfaces.connections import SendRequestDirective
from ask_sdk_model.services import ServiceException
from ask_sdk_model.services.reminder_management import Trigger, TriggerType, SpokenText, AlertInfo, SpokenInfo, \
    PushNotification, ReminderRequest, PushNotificationStatus
from ask_sdk_model.ui import SimpleCard
from ask_sdk_s3.adapter import S3Adapter


class SinoAliceQuery:

    @staticmethod
    def generate_english_time(diff):
        # The general concept here is to avoid "Spock Over-Accuracy"
        if diff.days > 0:
            sub_hours = math.floor((diff.seconds - 86400) / 60 / 60)
            plural_day = "days"
            if diff.days == 1:
                plural_day = "day"
            plural_hour = "hours"
            if sub_hours == 1:
                plural_hour = "hour"
            return str(diff.days) + " " + plural_day + " and " + str(sub_hours) + plural_hour
        else:
            hours = math.floor(diff.seconds / 60 / 60)
            plural_hour = "hours"
            if hours == 1:
                plural_hour = "hour"
            minutes = math.floor((diff.seconds / 60) - (hours * 60))
            plural_minute = "minutes"
            if minutes == 1:
                plural_minute = "minute"
            if hours > 0:
                hours_string = str(hours) + " " + plural_hour + " and "
            else:
                hours_string = ""
            return hours_string + str(minutes) + " " + plural_minute

    @staticmethod
    def next_event_time_in_minutes(delta_array, include_current_event):
        min_time = 0
        if include_current_event:
            min_time = -30
        next_event = 9999999999999
        for event in delta_array:
            utc_time = datetime.combine(datetime.utcnow(), datetime.min.time()) + event
            diff = utc_time - datetime.utcnow()
            min_until = diff.total_seconds() / 60
            # An event goes for 30 min, if it's less than 0, this means an event is happening now
            if min_time < min_until < next_event:
                next_event = min_until
        return next_event


    @staticmethod
    def upgrade_time():
        # Times from https://sinoalice.gamepedia.com/Events#Weapon_Guerrilla
        upgrade_times = [
            timedelta(hours=0, minutes=30),
            timedelta(hours=2, minutes=30),
            timedelta(hours=11, minutes=30),
            timedelta(hours=18, minutes=30),
            timedelta(hours=20, minutes=30),
            timedelta(hours=22, minutes=30),
            timedelta(days=1, minutes=30)
        ]

        next_event = SinoAliceQuery.next_event_time_in_minutes(upgrade_times, True)
        if next_event > 0:
            return "The next weapon and armor upgrade event is in " + \
                   SinoAliceQuery.generate_english_time(timedelta(minutes=next_event)) + "."
        else:
            return "There's a weapon and armor event happening right now. It ends in " + \
                   SinoAliceQuery.generate_english_time(timedelta(minutes=abs(next_event))) + "."

    @staticmethod
    def conquest_time():
        # Times from https://sinoalice.gamepedia.com/Events#Global_US
        upgrade_times = [
            timedelta(hours=1, minutes=30),
            timedelta(hours=3, minutes=30),
            timedelta(hours=12, minutes=0),
            timedelta(hours=19, minutes=30),
            timedelta(hours=21, minutes=30),
            timedelta(hours=23, minutes=30),
            timedelta(days=1, hours=1, minutes=30)
        ]

        next_event = SinoAliceQuery.next_event_time_in_minutes(upgrade_times, True)
        if next_event > 0:
            return "The next conquest event is in " + \
                   SinoAliceQuery.generate_english_time(timedelta(minutes=next_event)) + "."
        else:
            return "There's a conquest event happening right now. It ends in " + \
                   SinoAliceQuery.generate_english_time(timedelta(minutes=abs(next_event))) + "."


def increment_usage_count(handler_input):
    persistent_attr = handler_input.attributes_manager.persistent_attributes

    usage_count = 1
    if "UsageCount" in persistent_attr:
        usage_count += int(persistent_attr["UsageCount"])

    persistent_attr["UsageCount"] = usage_count
    handler_input.attributes_manager.save_persistent_attributes()


class LaunchRequestHandler(AbstractRequestHandler):
    """Handler for Skill Launch."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool

        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speak_output = "What do you want!"

        return (
            handler_input.response_builder
                         .speak(speak_output)
                         .ask(speak_output)
                         .response
        )


class UpgradeTimeIntentHandler(AbstractRequestHandler):
    """Handler for Upgrade Time Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("UpgradeTimeIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        increment_usage_count(handler_input)
        speak_output = SinoAliceQuery.upgrade_time()
        return (
            handler_input.response_builder
                         .speak(speak_output)
                         .response
        )


class ConquestTimeIntentHandler(AbstractRequestHandler):
    """Handler for Conquest Time Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("ConquestTimeIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        increment_usage_count(handler_input)
        speak_output = SinoAliceQuery.conquest_time()
        return (
            handler_input.response_builder
                         .speak(speak_output)
                         .response
        )


class SetUpgradeTimerIntentHandler(AbstractRequestHandler):
    """Handler for Set Upgrade Timer Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("SetUpgradeTimerIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        rb = handler_input.response_builder
        request_envelope = handler_input.request_envelope
        permissions = request_envelope.context.system.user.permissions

        if not (permissions and permissions.consent_token):
            return (
                rb.add_directive(
                    SendRequestDirective(
                        name="AskFor",
                        payload={
                            "@type": "AskForPermissionsConsentRequest",
                            "@version": "1",
                            "permissionScope": "alexa::alerts:reminders:skill:readwrite",
                        },
                        token=""
                    )
                ).response
            )

        reminder_service = handler_input.service_client_factory.get_reminder_management_service()

        upgrade_times = [
            timedelta(hours=0, minutes=30),
            timedelta(hours=2, minutes=30),
            timedelta(hours=11, minutes=30),
            timedelta(hours=18, minutes=30),
            timedelta(hours=20, minutes=30),
            timedelta(hours=22, minutes=30),
            timedelta(days=1, minutes=30)
        ]
        next_event = SinoAliceQuery.next_event_time_in_minutes(upgrade_times, False) - 1
        reminder_time = datetime.utcnow() + timedelta(minutes=next_event)
        notification_time = reminder_time.strftime("%Y-%m-%dT%H:%M:%S")

        trigger = Trigger(TriggerType.SCHEDULED_ABSOLUTE, notification_time, time_zone_id="Etc/UTC")
        text = SpokenText(locale='en-US',
                          ssml='<speak>The next weapon and armor upgrade event is about to begin!</speak>',
                          text='The next weapon and armor upgrade event is about to begin!')
        alert_info = AlertInfo(SpokenInfo([text]))
        push_notification = PushNotification(PushNotificationStatus.ENABLED)
        reminder_request = ReminderRequest(notification_time, trigger, alert_info, push_notification)

        try:
            reminder_response = reminder_service.create_reminder(reminder_request)
        except ServiceException as e:
            # see: https://developer.amazon.com/docs/smapi/alexa-reminders-api-reference.html#error-messages
            logger.error(e)
            raise e

        reminder_set_text = "Okay. I'll remind you in " + \
                            SinoAliceQuery.generate_english_time(timedelta(minutes=next_event)) + "."

        return rb.speak(reminder_set_text) \
            .set_card(SimpleCard("Weapon / Armor Event Reminder", reminder_set_text)) \
            .set_should_end_session(True) \
            .response


class SetConquestTimerIntentHandler(AbstractRequestHandler):
    """Handler for Set Conquest Timer Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("SetConquestTimerIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        rb = handler_input.response_builder
        request_envelope = handler_input.request_envelope
        permissions = request_envelope.context.system.user.permissions

        if not (permissions and permissions.consent_token):
            return (
                rb.add_directive(
                    SendRequestDirective(
                        name="AskFor",
                        payload={
                            "@type": "AskForPermissionsConsentRequest",
                            "@version": "1",
                            "permissionScope": "alexa::alerts:reminders:skill:readwrite",
                        },
                        token=""
                    )
                ).response
            )

        reminder_service = handler_input.service_client_factory.get_reminder_management_service()

        upgrade_times = [
            timedelta(hours=1, minutes=30),
            timedelta(hours=3, minutes=30),
            timedelta(hours=12, minutes=0),
            timedelta(hours=19, minutes=30),
            timedelta(hours=21, minutes=30),
            timedelta(hours=23, minutes=30),
            timedelta(days=1, hours=1, minutes=30)
        ]
        next_event = SinoAliceQuery.next_event_time_in_minutes(upgrade_times, False) - 1
        reminder_time = datetime.utcnow() + timedelta(minutes=next_event)
        notification_time = reminder_time.strftime("%Y-%m-%dT%H:%M:%S")

        trigger = Trigger(TriggerType.SCHEDULED_ABSOLUTE, notification_time, time_zone_id="Etc/UTC")
        text = SpokenText(locale='en-US',
                          ssml='<speak>The next conquest event is about to begin!</speak>',
                          text='The next conquest event is about to begin!')
        alert_info = AlertInfo(SpokenInfo([text]))
        push_notification = PushNotification(PushNotificationStatus.ENABLED)
        reminder_request = ReminderRequest(notification_time, trigger, alert_info, push_notification)

        try:
            reminder_response = reminder_service.create_reminder(reminder_request)
        except ServiceException as e:
            # see: https://developer.amazon.com/docs/smapi/alexa-reminders-api-reference.html#error-messages
            logger.error(e)
            raise e

        reminder_set_text = "Okay. I'll remind you in " + \
                            SinoAliceQuery.generate_english_time(timedelta(minutes=next_event)) + "."

        return rb.speak(reminder_set_text) \
            .set_card(SimpleCard("Conquest Event Reminder", reminder_set_text)) \
            .set_should_end_session(True) \
            .response


class HelpIntentHandler(AbstractRequestHandler):
    """Handler for Help Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speak_output = "You can ask me about many things in Warframe. For example: What is the current Arbitration? " \
                       "What is the weather in the Orb Vallis? How long until it's night in Cetus? How long until " \
                       "<phoneme alphabet=\"ipa\" ph=\"bero\">Baro</phoneme> arrives? If you want to know about a " \
                       "specific fissure type, ask something like: How many survivals are there? If you want to " \
                       "check if there's a rare Invasion going on, ask: Are there any Invasions worth doing? By " \
                       "default, I'll give you information on the PC version of the game. If you want to switch to" \
                       " a console just say \"Change platforms\". So, what would you like?"

        help_samples = "What is the current Arbitration?\nWhat is the weather in the Orb Vallis?\nHow long until " \
                       "it's night in Cetus?\nHow long until Baro arrives?\nHow many survivals are there?\nAre " \
                       "there any Invasions worth doing?"

        if hasattr(handler_input.request_envelope.context.system.device.supported_interfaces, 'display'):
            return (handler_input.response_builder
                    .set_card(SimpleCard("Example Questions", help_samples))
                    .speak(speak_output)
                    .ask(speak_output)
                    .response
                    )

        return (
            handler_input.response_builder
                         .speak(speak_output)
                         .ask(speak_output)
                         .response
        )


class CanFulfillIntentRequestHandler(AbstractRequestHandler):
    """Handler for CanFulfillIntentRequest."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type('CanFulfillIntentRequest')(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        can_fulfill = CanFulfillIntent(CanFulfillIntentValues.YES)
        if ask_utils.is_intent_name("ChangePlatformsIntent")(handler_input):
            can_fulfill = CanFulfillIntent(CanFulfillIntentValues.NO)

        return (
            handler_input.response_builder
                         .set_can_fulfill_intent(can_fulfill)
                         .response
        )


class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Single handler for Cancel and Stop Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input) or
                ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speak_output = "Goodbye!"

        return (
            handler_input.response_builder
                         .speak(speak_output)
                         .response
        )


class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handler for Session End."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        # Any cleanup logic goes here.

        return handler_input.response_builder.response


class IntentReflectorHandler(AbstractRequestHandler):
    """The intent reflector is used for interaction model testing and debugging.
    It will simply repeat the intent the user said. You can create custom handlers
    for your intents by defining them above, then also adding them to the request
    handler chain below.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("IntentRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        intent_name = ask_utils.get_intent_name(handler_input)
        speak_output = "You just triggered " + intent_name + "."

        return (
            handler_input.response_builder
                         .speak(speak_output)
                         .response
        )


class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Generic error handling to capture any syntax or routing errors. If you receive an error
    stating the request handler chain is not found, you have not implemented a handler for
    the intent being invoked or included it in the skill builder below.
    """
    def can_handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> bool
        return True

    def handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> Response
        logger.error(exception, exc_info=True)

        speak_output = "Sorry, I had trouble doing what you asked. Please try again."

        return (
            handler_input.response_builder
                         .speak(speak_output)
                         .ask(speak_output)
                         .response
        )


s3_adapter = S3Adapter(bucket_name=os.environ["S3_PERSISTENCE_BUCKET"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# The SkillBuilder object acts as the entry point for your skill, routing all request and response
# payloads to the handlers above. Make sure any new handlers or interceptors you've
# defined are included below. The order matters - they're processed top to bottom.
sb = CustomSkillBuilder(persistence_adapter=s3_adapter, api_client=DefaultApiClient())

sb.add_request_handler(CanFulfillIntentRequestHandler())

sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(UpgradeTimeIntentHandler())
sb.add_request_handler(ConquestTimeIntentHandler())
sb.add_request_handler(SetUpgradeTimerIntentHandler())
sb.add_request_handler(SetConquestTimerIntentHandler())

sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
# make sure IntentReflectorHandler is last so it doesn't override your custom intent handlers
sb.add_request_handler(IntentReflectorHandler())

sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
