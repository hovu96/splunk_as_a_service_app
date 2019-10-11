
require([
    "jquery",
    "splunkjs/ready!"
],
    function ($, _) {

        $(".dashboard-view-controls").append($('<button class="btn btn-primary action-button">Add App</button>').click(function () {
            //window.location.href = 'cluster';
        }));

    }
);