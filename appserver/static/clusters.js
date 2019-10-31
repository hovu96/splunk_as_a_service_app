
require([
    "jquery",
    "splunkjs/ready!"
],
    function ($, _) {
        const addButton = $("<div></div>");
        $(".dashboard-view-controls").append(addButton);
        addButton.append($("<button class=\"btn btn-primary action-button\">Add Cluster</button>").click(async function () {
            window.location.href = 'cluster';
        }))
    }
);