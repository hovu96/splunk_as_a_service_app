
require([
    "jquery",
    "splunkjs/ready!"
],
    function ($) {
        $(".dashboard-view-controls").append($('<button class="btn btn-primary action-button">Add App</button>').click(function () {
            window.location.href = 'app_add';
        }));
    }
);