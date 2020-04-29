const appName = Splunk.util.getPath().match(`\/app\/(.+)\/.+`)[1];

require([
    "jquery",
    Splunk.util.make_url(`/static/app/${appName}/utils.js`),
    "splunkjs/mvc",
    "splunkjs/ready!"
], function (
    $,
    Utils,
    mvc,
    _,
    ) {
        var endpoint = Utils.createRestEndpoint();
        const tokens = mvc.Components.getInstance("submitted");
        const testID = tokens.attributes.test_id;

        const titleElement = $(".dashboard-title.dashboard-header-title");
        titleElement.text(titleElement.text() + ": " + testID);

        const backButton = $('<button class="btn action-button">Back</button>');
        backButton.click(async function () {
            window.location.href = 'performance_tests';
        });
        $(".dashboard-view-controls").append(backButton);

        const stopButton = $('<button class="btn btn-primary action-button" style="background-color: red; display: none">Stop</button>');
        stopButton.click(async function () {
            const progressIndicator = Utils.newLoadingIndicator({
                title: "Stopping Performance Test ...",
                subtitle: "Please wait.",
            });
            try {
                await endpoint.delAsync('performance_test/' + testID, {
                });
                progressIndicator.hide();
                window.location.href = 'performance_tests';
            }
            catch (err) {
                progressIndicator.hide();
                await Utils.showErrorDialog(null, err, true).wait();
            }
        });
        $(".dashboard-view-controls").append(stopButton);

        const statusSearchManager = mvc.Components.getInstance("status_search");
        var statusResults = statusSearchManager.data("results");
        statusResults.on("data", function () {
            const statusIndex = statusResults.data().fields.indexOf("status");
            const status = statusResults.data().rows[0][statusIndex];
            if (status == "Finished") {
                stopButton.css("display", "none");
            } else {
                stopButton.css("display", "block");
            }
        });
    }
);