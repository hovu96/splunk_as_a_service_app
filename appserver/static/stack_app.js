const appName = Splunk.util.getPath().match(`\/app\/(.+)\/.+`)[1];

require([
    "jquery",
    Splunk.util.make_url(`/static/app/${appName}/modal.js`),
    Splunk.util.make_url(`/static/app/${appName}/utils.js`),
    "splunkjs/mvc",
    'splunkjs/mvc/simplexml/ready!',
], function (
    $,
    Modal,
    Utils,
    mvc,
    _
) {
    var endpoint = Utils.createRestEndpoint();

    const titleElement = $(".dashboard-title.dashboard-header-title");

    const tokens = mvc.Components.getInstance("submitted");
    const appName = tokens.attributes.name;
    const appVersion = tokens.attributes.version;
    const stackID = tokens.attributes.stack;

    const initialTitle = titleElement.text();
    const updateTitle = function (title) {
        titleElement.text(initialTitle + ": " + title);
    };
    updateTitle(appName);

    const backButton = $('<button class="btn action-button">Back</button>');
    backButton.click(function () {
        if (tokens.attributes.back && tokens.attributes.back == "app") {
            window.location.href = 'app?name=' + appName + "&version=" + appVersion;
        } else {
            window.location.href = 'stack?id=' + stackID;
        }
    });
    $(".dashboard-view-controls").append(backButton);

    var appURLPath = 'app/' + appName + "/" + appVersion;
    endpoint.get(appURLPath, {}, async function (err, response) {
        if (err) {
            Utils.showErrorDialog("Error loading app details", err).footer.append($('<button>Retry</button>').attr({
                type: 'button',
                class: "btn btn-primary",
            }).on('click', function () {
                window.location.reload();
            }));
            return;
        }
        const app = await Utils.getResponseContent(response);
        updateTitle(app.title);
    });

    $("#edit-config-button").click(function () {
        window.location.href = "app_deploy?name=" + encodeURIComponent(appName) +
            "&version=" + encodeURIComponent(appVersion) +
            "&stack=" + encodeURIComponent(stackID);
    });

    const undeployButton = $('<button class="btn btn-primary action-button" style="background-color: red;">Undeploy</button>');
    undeployButton.click(async function () {
        const progressIndicator = Utils.newLoadingIndicator({
            title: "Undeploying App...",
            subtitle: "Please wait.",
        });
        try {
            await endpoint.delAsync('stack_app/' + stackID + "/" + appName);
            backButton.click();
        }
        catch (err) {
            progressIndicator.hide();
            await Utils.showErrorDialog(null, err, true).wait();
        }
    });
    $(".dashboard-view-controls").append(undeployButton);
});
