
require([
    "jquery",
    "splunkjs/ready!"
],
    function ($, _) {
        const addButton = $("<div id=\"addButton\"></div>");
        $(".dashboard-view-controls").append(addButton);
        addButton.append($("<button class=\"btn btn-primary\">Add Cluster</button>").click(async function () {
            window.location.href = 'cluster';
        }))
    }
);