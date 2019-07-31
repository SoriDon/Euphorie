# coding=utf-8
from Acquisition import aq_inner
from euphorie.client import model
from euphorie.client.navigation import FindNextQuestion
from euphorie.client.navigation import FindPreviousQuestion
from euphorie.client.navigation import getTreeData
from euphorie.client.navigation import QuestionURL
from euphorie.client.update import wasSurveyUpdated
from euphorie.client.utils import HasText
from euphorie.content.interfaces import ICustomRisksModule
from euphorie.content.profilequestion import IProfileQuestion
from logging import getLogger
from plone import api
from plone.memoize.view import memoize
from Products.Five import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from sqlalchemy import sql
from z3c.saconfig import Session


logger = getLogger(__name__)


class Mixin(object):

    def get_custom_risks(self):
        session = self.context.aq_parent.session
        query = Session.query(model.Risk).filter(
            sql.and_(
                model.Risk.is_custom_risk == 't',
                model.Risk.path.startswith(model.Module.path),
                model.Risk.session_id == session.id
            )
        ).order_by(model.Risk.id)
        return query.all()


class IdentificationView(BrowserView, Mixin):
    """The introduction page for a module.
    """
    variation_class = "variation-risk-assessment"
    phase = "identification"
    question_filter = None
    template = ViewPageTemplateFile('templates/module_identification.pt')

    @property
    @memoize
    def webhelpers(self):
        return api.content.get_view("webhelpers", self.context, self.request)

    @property
    def tree(self):
        return getTreeData(
            self.request,
            self.context,
            survey=self.context.aq_parent.aq_parent
        )

    @property
    @memoize
    def next_question(self):
        """ Try to understand what the next question will be
        """
        return FindNextQuestion(
            self.context,
            dbsession=self.context.aq_parent.session,
            filter=self.question_filter,
        )

    @property
    @memoize
    def next_question_url(self):
        """ Return the URL to the next question
        """
        if not self.next_question:
            return ""
        return "{parent_url}/{next_question_id}/@@{view}".format(
            parent_url=self.context.aq_parent.absolute_url(),
            next_question_id=self.next_question.id,
            view=self.__name__,
        )

    @property
    @memoize
    def next_phase_url(self):
        """ Return the URL to the next question
        """
        return "{parent_url}/@@actionplan".format(
            parent_url=self.context.aq_parent.absolute_url(),
        )

    def __call__(self):
        # Render the page only if the user has edit rights,
        # otherwise redirect to the start page of the session.
        start_view = api.content.get_view(
            "start",
            self.context.aq_parent,
            self.request,
        )
        if not start_view.can_edit_session:
            return self.request.response.redirect(
                self.context.aq_parent.absolute_url() + '/@@start'
            )

        survey = self.context.aq_parent.aq_parent

        if self.webhelpers.redirectOnSurveyUpdate():
            return

        context = aq_inner(self.context)
        module = survey.restrictedTraverse(context.zodb_path.split("/"))
        if self.request.environ["REQUEST_METHOD"] == "POST":
            return self.save_and_continue(module)

        if IProfileQuestion.providedBy(module) and context.depth == 2:

            if self.next_question is None:
                url = self.next_phase_url
            else:
                url = self.next_question_url
            return self.request.response.redirect(url)

        self.title = module.title
        self.module = module
        number_files = 0
        for i in range(1, 5):
            number_files += getattr(
                self.module, 'file{0}'.format(i), None) and 1 or 0
        self.has_files = number_files > 0
        self.next_is_actionplan = not self.next_question
        if ICustomRisksModule.providedBy(module):
            template = ViewPageTemplateFile(
                'templates/module_identification_custom.pt'
            ).__get__(self, "")
        else:
            template = self.template
        return template()

    def save_and_continue(self, module):
        """ We received a POST request.
            Submit the form and figure out where to go next.
        """
        context = aq_inner(self.context)
        reply = self.request.form
        if module.optional:
            if "skip_children" in reply:
                context.skip_children = reply.get("skip_children")
                context.postponed = False
            else:
                context.postponed = True
            self.aq_parent.session.touch()

        if reply.get("next") == "previous":
            if self.next_question is None:
                # We ran out of questions, step back to intro page
                url = "%s/@@identification" % self.context.aq_parent.absolute_url()
                self.request.response.redirect(url)
                return
        else:
            if ICustomRisksModule.providedBy(module):
                if reply["next"] == "add_custom_risk":
                    risk_id = self.add_custom_risk()
                    url = "{parent_url}/{risk_id}/@@identification".format(
                        parent_url=self.context.aq_parent.absolute_url(),
                        risk_id=risk_id,
                    )
                    return self.request.response.redirect(url)
                else:
                    # We ran out of questions, proceed to the action plan
                    return self.request.response.redirect(self.next_phase_url)
            if self.next_question is None:
                # We ran out of questions, proceed to the action plan
                return self.request.response.redirect(self.next_phase_url)

        self.request.response.redirect(self.next_question_url)

    def add_custom_risk(self):

        session = self.context.aq_parent.session
        sql_risks = self.context.children()
        if sql_risks.count():
            counter_id = max(
                [int(risk.path[-3:]) for risk in sql_risks.all()]) + 1
        else:
            counter_id = 1

        # Add a new risk
        risk = model.Risk(
            comment="",
            priority=None,
            risk_id=None,
            risk_type='risk',
            skip_evaluation=True,
            title="",
            identification=None,
            training_notes="",
            custom_description="",
        )
        risk.is_custom_risk = True
        risk.skip_children = False
        risk.postponed = False
        risk.has_description = None
        risk.zodb_path = "/".join(
            [session.zodb_path] +
            [self.context.zodb_path] +
            # There's a constraint for unique zodb_path per session
            ['%d' % counter_id]
        )
        risk.profile_index = 0  # XXX: not sure what this is for
        self.context.addChild(risk)
        return counter_id


class ActionPlanView(BrowserView):
    """The introduction page for an :obj:`euphorie.content.module` in an action
    plan.

    """
    variation_class = "variation-risk-assessment"
    phase = "actionplan"
    question_filter = model.ACTION_PLAN_FILTER

    @property
    @memoize
    def webhelpers(self):
        return self.context.restrictedTraverse('webhelpers')

    @property
    def use_solution_direction(self):
        return HasText(getattr(self.module, "solution_direction", None))

    @property
    @memoize
    def module(self):
        return self.context.aq_parent.aq_parent.restrictedTraverse(
            self.context.zodb_path.split("/")
        )

    @property
    def tree(self):
        return getTreeData(
            self.request,
            self.context,
            filter=self.question_filter,
            phase=self.phase,
            survey=self.context.aq_parent,
        )

    def __call__(self):
        # Render the page only if the user has edit rights,
        # otherwise redirect to the start page of the session.
        start_view = api.content.get_view(
            "start",
            self.context.aq_parent,
            self.request,
        )
        if not start_view.can_edit_session:
            return self.request.response.redirect(
                self.context.aq_parent.aq_parent.absolute_url() + '/@@start'
            )
        if self.webhelpers.redirectOnSurveyUpdate():
            return
        if self.request.environ["REQUEST_METHOD"] == "POST":
            return self._update()

        context = aq_inner(self.context)
        if (
            (IProfileQuestion.providedBy(self.module) and context.depth == 2) or
            (
                ICustomRisksModule.providedBy(self.module) and
                self.phase == 'actionplan'
            )
        ):
            next_question = FindNextQuestion(context, filter=self.question_filter)
            if next_question is None:
                if self.phase == 'identification':
                    url = "%s/@@actionplan" % self.context.aq_parent.absolute_url()
                elif self.phase == 'evaluation':
                    url = "%s/actionplan" % self.context.aq_parent.absolute_url()
                elif self.phase == 'actionplan':
                    url = "%s/@@report" % self.context.aq_parent.absolute_url()
            else:
                url = "{session_url}/{id}/@@actionplan".format(
                    session_url=self.context.aq_parent.absolute_url(),
                    id=next_question.id,
                )
            return self.request.response.redirect(url)

        self.title = self.context.title
        previous = FindPreviousQuestion(
            self.context, filter=self.question_filter)
        if previous is None:
            self.previous_url = "%s/@@%s" % (
                self.context.aq_parent.absolute_url(), self.phase
            )
        else:
            self.previous_url = "{session_url}/{id}/@@{phase}".format(
                session_url=self.context.aq_parent.absolute_url(),
                id=previous.id,
                pahse=self.phase,
            )

        next_question = FindNextQuestion(self.context, filter=self.question_filter)
        if next_question is None:
            self.next_url = "%s/@@report" % (
                self.context.aq_parent.absolute_url()
            )
        else:
            self.next_url = "{session_url}/{id}/@@{phase}".format(
                session_url=self.context.aq_parent.absolute_url(),
                id=next_question.id,
                pahse=self.phase,
            )
        return self.index()
