const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    "jquery",
    "/static/app/" + appName + "/utils.js",
    "/static/app/" + appName + "/modal.js",
    "splunkjs/mvc",
    "splunkjs/ready!"
], function (
    $,
    Utils,
    Modal,
    mvc,
    _
) {
    var endpoint = Utils.createRestEndpoint();
    const tokens = mvc.Components.getInstance("submitted");
    const deploymentID = tokens.attributes.id;

    endpoint.get('stack/' + deploymentID, {}, function (err, response) {
        if (err) {
            Utils.showErrorDialog(null, err).footer.append($('<button>Reload</button>').attr({
                type: 'button',
                class: "btn btn-primary",
            }).on('click', function () {
                window.location.reload();
            }));
            return;
        }
        Utils.getResponseContent(response).then(function (deployment) {
            var title;
            if (deployment.title) {
                title = deployment.title;
            } else {
                title = deploymentID;
            }
            const titleElement = $(".dashboard-title.dashboard-header-title");
            titleElement.text(titleElement.text() + ": " + title);
        });
    });

    const backButton = $('<button class="btn action-button">Back</button>');
    backButton.click(async function () {
        window.location.href = 'stacks';
    });
    $(".dashboard-view-controls").append(backButton);

    const deleteButton = $('<button class="btn btn-primary action-button" style="background-color: red;">Delete</button>');
    deleteButton.click(function () {
        const modal = new Modal("delete-dialog-body", {
            title: 'Delete Deployment',
            backdrop: 'static',
            keyboard: false,
            destroyOnHide: true,
            type: 'normal',
        });
        modal.body.append($(`
            <p>
                Deleting a Splunk Deployment deletes all configuration as well all data received by Splunk.
            </p>
            <p>
                Users won\'t be able to login to Splunk after deleting the deployment.
            </p>
            <p>
                <input id="force-delete" type="checkbox">Force Delete</input>
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
                title: "Deleting Splunk Deployment...",
                subtitle: "Please wait.",
            });
            try {
                await endpoint.delAsync('stack/' + deploymentID, {
                    force: $("#force-delete").prop("checked"),
                });
                progressIndicator.hide();
                window.location.href = 'stacks';
            }
            catch (err) {
                progressIndicator.hide();
                await Utils.showErrorDialog(null, err, true).wait();
            }
        }));
        modal.show();
    });
    $(".dashboard-view-controls").append(deleteButton);

    const passwordButton = $('<button class="btn action-button">Credentials</button>');
    passwordButton.click(async function () {
        const progressIndicator = Utils.newLoadingIndicator({
            title: "Retrieving Credentials...",
            subtitle: "Please wait.",
        });
        var credentials;
        try {
            const response = await endpoint.getAsync('credentials/' + deploymentID);
            credentials = await Utils.getResponseContent(response);
            progressIndicator.hide();
        }
        catch (err) {
            progressIndicator.hide();
            await Utils.showErrorDialog(null, err, true).wait();
            return;
        }

        const modal = new Modal("show-password", {
            title: 'Access Credentials',
            backdrop: 'static',
            destroyOnHide: true,
            type: 'normal',
        });
        const table = $(`
            <table class="credentials">
                <tr>
                    <td class="name">Username:</td>
                    <td class="value">admin</td>
                </tr>
                <tr>
                    <td class="name">Password:</td>
                    <td class="value admin_password"></td>
                </tr>
            </table>
            `);
        $(".admin_password", table).text(credentials.admin)
        modal.body.append(table);
        modal.footer.append($('<button>Close</button>').attr({
            type: 'button',
            'data-dismiss': 'modal',
            class: "btn btn-primary",
        }));
        modal.show();
    });
    $(".dashboard-view-controls").append(passwordButton);

}
);