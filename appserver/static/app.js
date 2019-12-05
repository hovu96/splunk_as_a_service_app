const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    "jquery",
    "/static/app/" + appName + "/modal.js",
    "/static/app/" + appName + "/utils.js",
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

    const initialTitle = titleElement.text();
    const updateTitle = function (title) {
        titleElement.text(initialTitle + ": " + title + " (" + appVersion + ")");
    };
    updateTitle(appName);

    const backButton = $('<button class="btn action-button">Back</button>');
    backButton.click(async function () {
        window.location.href = 'apps';
    });
    $(".dashboard-view-controls").append(backButton);

    const deployButton = $('<button class="btn btn-primary action-button">Deploy</button>');
    deployButton.click(function () {
        window.location.href = "app_deploy?name=" + encodeURIComponent(appName) + "&version=" + encodeURIComponent(appVersion);
    });
    $(".dashboard-view-controls").append(deployButton);

    var appURLPath = 'app/' + appName + "/" + appVersion;
    endpoint.get(appURLPath, {}, function (err, response) {
        if (err) {
            Utils.showErrorDialog("Error loading app details", err).footer.append($('<button>Retry</button>').attr({
                type: 'button',
                class: "btn btn-primary",
            }).on('click', function () {
                window.location.reload();
            }));
            return;
        }
        updateTitle(response.data.title);
    });

    const deleteButton = $('<button class="btn btn-primary action-button" style="background-color: red;">Delete</button>');
    deleteButton.click(function () {
        const modal = new Modal("delete-dialog-body", {
            title: 'Delete App',
            backdrop: 'static',
            keyboard: false,
            destroyOnHide: true,
            type: 'normal',
        });
        modal.body.append($(`
            <p>
                Deleting an app from this list does not deletes the app
                in stacks to which it has been deployed to.
            </p>
            `));
        modal.footer.append($('<button>Cancel</button>').attr({
            type: 'button',
            'data-dismiss': 'modal',
            class: "btn",
        }));
        modal.footer.append($('<button>Delete</button>').attr({
            type: 'button',
            'data-dismiss': 'modal',
            class: "btn btn-primary",
        }).css({
            "background-color": "red",
        }).click(async function () {
            const progressIndicator = Utils.newLoadingIndicator({
                title: "Deleting App...",
                subtitle: "Please wait.",
            });
            try {
                await endpoint.delAsync('app/' + appName + "/" + appVersion);
                progressIndicator.hide();
                window.location.href = 'apps';
            }
            catch (err) {
                progressIndicator.hide();
                await Utils.showErrorDialog(null, err, true).wait();
            }
        }));
        modal.show();
    });
    $(".dashboard-view-controls").append(deleteButton);
});
