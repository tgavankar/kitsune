/*
 * Voting form ajaxified.
 */

(function($) {

"use strict";

function AjaxVote(form, options) {
    /* Args:
     * form - the voting form to ajaxify. Can be a selector, DOM element,
     *        or jQuery node
     * options - dict of options
     *      positionMessage - absolutely position the response message?
     *      removeForm - remove the form after vote?
     */
    AjaxVote.prototype.init.call(this, form, options);
}

AjaxVote.prototype = {
    init: function(form, options) {
        var self = this,
            $form = $(form),
            $btns = $form.find('input[type="submit"]');

        options = $.extend({
            positionMessage: false,
            removeForm: false,
            replaceFormWithMessage: false
        }, options);
        self.options = options;
        self.voted = false;
        self.$form = $form;

        $btns.click(function(e) {
            if (!self.voted) {
                var $btn = $(this),
                    $form = $btn.closest('form'),
                    formDataArray = $form.serializeArray(),
                    data = {},
                    i, l;
                $btns.attr('disabled', 'disabled');
                $form.addClass('busy');
                for (i = 0, l = formDataArray.length; i < l; i++) {
                    data[formDataArray[i].name] = formDataArray[i].value;
                }
                data[$btn.attr('name')] = $btn.val();
                $.ajax({
                    url: $btn.closest('form').attr('action'),
                    type: 'POST',
                    data: data,
                    dataType: 'json',
                    success: function(data) {
                        if (data.survey) {
                            self.showSurvey(data.survey, $form.parent());
                        } else {
                            self.showMessage(data.message, $btn, $form);
                        }
                        $btn.addClass('active');
                        $btns.removeAttr('disabled');
                        $form.removeClass('busy');
                        self.voted = true;
                    },
                    error: function() {
                        var msg = gettext('There was an error submitting your vote.');
                        self.showMessage(msg, $btn);
                        $btns.removeAttr('disabled');
                        $form.removeClass('busy');
                    }
               });
            }

            $(this).blur();
            e.preventDefault();
            return false;
        });
    },
    showMessage: function(message, $showAbove, $form) {
        // TODO: Tweak KBox to handle this case.
        var self = this,
            $html = $('<div class="ajax-vote-box"><p></p></div>'),
            offset = $showAbove.offset();
        $html.find('p').html(message);

        if (self.options.positionMessage) {
            // on desktop browsers we use absolute positioning
            $('body').append($html);
            $html.css({
                top: offset.top - $html.height() - 30,
                left: offset.left + $showAbove.width()/2 - $html.width()/2
            });
            var timer = setTimeout(fadeOut, 10000);
            $('body').one('click', fadeOut);
        } else if (self.options.replaceFormWithMessage) {
            $form.replaceWith($html.removeClass('ajax-vote-box'));
        } else {
            // on mobile browsers we just append to the grandfather
            // TODO: make this more configurable with an extra option
            $showAbove.parent().parent()
                .addClass($showAbove.val()).append($html);
        }

        function fadeOut() {
            $html.fadeOut(function(){
                $html.remove();
            });
            if (self.options.removeForm) {
                self.$form.fadeOut(function(){
                    self.$form.remove();
                });
            }
            $('body').unbind('click', fadeOut);
            clearTimeout(timer);
        }
    },
    showSurvey: function(survey, $container) {
        var self = this,
            $survey = $(survey);

        $container.after($survey);

        // If we are in the sidebar, remove the vote form container.
        if ($container.closest('#side').length) {
            $container.remove();
        }

        new k.AjaxVote($survey.find('form'), {
            replaceFormWithMessage: true
        });
    }
};

window.k = window.k || {};
window.k.AjaxVote = AjaxVote;

})(jQuery);