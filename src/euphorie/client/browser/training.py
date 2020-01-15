# coding=utf-8
from collections import OrderedDict
from datetime import date
from euphorie.client import survey
from euphorie.client import utils as client_utils
from json import loads
from logging import getLogger
from plone import api
from plone.memoize.instance import memoize
from Products.CMFPlone.utils import safe_unicode
from Products.Five import BrowserView
import markdown

logger = getLogger(__name__)


class TrainingSlide(BrowserView):
    """ Template / macro to hold the training slide markup
    Currently not active in default Euphorie
    """

    @property
    @memoize
    def webhelpers(self):
        return api.content.get_view("webhelpers", self.context, self.request)

    @property
    @memoize
    def is_custom(self):
        return "custom-risks" in self.context.zodb_path

    @property
    @memoize
    def item_type(self):
        return self.context.type

    @property
    @memoize
    def zodb_elem(self):
        if self.is_custom:
            return None
        return self.context.aq_parent.restrictedTraverse(
            self.context.zodb_path.split("/")
        )

    @property
    @memoize
    def for_download(self):
        return "for_download" in self.request and self.request["for_download"]

    @property
    def number(self):
        if self.is_custom:
            num_elems = self.context.number.split(".")
            number = u".".join([u"Ω"] + num_elems[1:])
        else:
            number = self.context.number
        if self.item_type == "module":
            number = u"{}.0".format(number)
        return number

    @property
    def slide_title(self):
        if self.is_custom and self.item_type == "module":
            return client_utils.get_translated_custom_risks_title(self.request)
        return self.context.title

    @property
    def slide_template(self):
        if self.item_type == "module":
            return "template-module"
        if self.description or self.image:
            return "template-two-column"
        return "template-default"

    @property
    def slide_type(self):
        # Perhaps this will not be needed any more...
        return self.item_type

    @property
    def slide_date(self):
        return date.today().strftime("%Y-%m-%d")

    @property
    def department(self):
        # XXX tbd - maybe in webhelpers?
        return "-"

    @property
    def description(self):
        if self.is_custom:
            return getattr(self.context, "custom_description", "") or ""
        return self.zodb_elem.description or ""

    @property
    def training_notes(self):
        training_notes = getattr(self.context, "training_notes", "") or ""
        if self.for_download:
            training_notes = markdown.markdown(training_notes)
        return training_notes

    @property
    def existing_measures(self):
        if self.item_type != "risk":
            return []
        try:
            existing_measures = loads(self.context.existing_measures)
            # Backwards compat. We used to save dicts in JSON before we
            # switched to list of tuples.
            if isinstance(existing_measures, dict):
                existing_measures.items()
            existing_measures = [
                text.strip() for (text, active) in existing_measures if active
            ]
            return existing_measures
        except:
            logger.warning(
                "Saved existing_measures could not be retrieved on %s",
                self.context.absolute_url(),
            )
            return []

    @property
    def image(self):
        if self.is_custom:
            if not getattr(self.context, "image_data", None):
                return None
            _view = self.context.__of__(
                self.webhelpers.traversed_session.aq_parent["custom-risks"]
            ).restrictedTraverse("image-display")
            return _view.get_or_create_image_scaled()
        image = self.zodb_elem.image and self.zodb_elem.image.data or None
        if image and self.for_download:
            try:
                scales = self.zodb_elem.restrictedTraverse("images", None)
                if scales:
                    if self.item_type == "module":
                        scale_name = "training_title"
                    else:
                        scale_name = "training"
                    scale = scales.scale(fieldname="image", scale=scale_name)
                    if scale and scale.data:
                        image = scale.data.data
            except:
                image = None
                logger.warning(
                    "Image data could not be fetched on %s", self.context.absolute_url()
                )
        return image

    def slides(self):
        slides = [{"slide_type": self.item_type, "slide_template": self.slide_template}]
        if self.existing_measures:
            slides.append(
                {
                    "slide_type": "risk_measures",
                    "content": self.existing_measures,
                    "slide_template": "template-measures",
                }
            )
        return slides


class TrainingView(BrowserView, survey._StatusHelper):
    """ The view that shows the main-menu Training module
    Currently not active in default Euphorie
    """

    variation_class = "variation-risk-assessment"
    skip_unanswered = False
    for_download = False

    @property
    @memoize
    def webhelpers(self):
        return self.context.restrictedTraverse("webhelpers")

    @property
    @memoize
    def session(self):
        """ Return the session for this context/request
        """
        return self.context.session

    @property
    @memoize
    def title_image(self):
        try:
            return self.context.aq_parent.external_site_logo.data
        except AttributeError:
            logger.warning(
                "Image data (logo) could not be fetched on survey  %s",
                self.context.absolute_url(),
            )
            return

    @property
    @memoize
    def slide_data(self):
        modules = self.getModulePaths()
        risks = self.getRisks(modules, skip_unanswered=self.skip_unanswered)
        seen_modules = []
        data = OrderedDict()
        for (module, risk) in risks:
            module_path = module.path
            if module_path not in seen_modules:
                module_in_context = module.__of__(self.webhelpers.traversed_session)
                module_in_context.REQUEST["for_download"] = self.for_download
                _view = module_in_context.restrictedTraverse("training_slide")
                slides = _view.slides()
                data.update(
                    {
                        module_path: {
                            "item": module_in_context,
                            "training_view": _view,
                            "slides": slides,
                        }
                    }
                )
                seen_modules.append(module_path)
            risk_in_context = risk.__of__(self.webhelpers.traversed_session)
            risk_in_context.REQUEST["for_download"] = self.for_download
            _view = risk_in_context.restrictedTraverse("training_slide")
            slides = _view.slides()
            data.update(
                {
                    risk.path: {
                        "item": risk_in_context,
                        "training_view": _view,
                        "slides": slides,
                    }
                }
            )
        return data

    @property
    def slide_total_count(self):
        # The title slide is not part of the dataset, therefore start with 1
        count = 1
        for data in self.slide_data.values():
            count += len(data["slides"])
        return count

    def __call__(self):
        if self.webhelpers.redirectOnSurveyUpdate():
            return

        if self.request.environ["REQUEST_METHOD"] == "POST":
            for entry in self.request.form:
                if entry.startswith("training_notes"):
                    index = entry.split("-")[-1]
                    sql_item = self.slide_data[index]
                    value = safe_unicode(self.request[entry])
                    sql_item.training_notes = value
            self.webhelpers.traversed_session.session.touch()

        return self.index()
