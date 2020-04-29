const appName = Splunk.util.getPath().match(`\/app\/(.+)\/.+`)[1];

require([
    "jquery",
    Splunk.util.make_url(`/static/app/${appName}/utils.js`),
    Splunk.util.make_url(`/static/app/${appName}/modal.js`),
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
    const stackID = tokens.attributes.id;

    const titleElement = $(".dashboard-title.dashboard-header-title");
    const initialTitle = titleElement.text();
    const updateStackTitle = function () {
        endpoint.get('stack/' + stackID, {}, function (err, response) {
            if (err) {
                Utils.showErrorDialog(null, err).footer.append($('<button>Reload</button>').attr({
                    type: 'button',
                    class: "btn btn-primary",
                }).on('click', function () {
                    window.location.reload();
                }));
                return;
            }
            Utils.getResponseContent(response).then(function (stack) {
                titleElement.text(initialTitle + ": " + stack.title);
                $('#rename-dialog input[name="title"]').val(stack.title);
            });
        });
    };
    updateStackTitle();

    $('#rename-button').click(function () {
        const modal = new Modal("rename-dialog", {
            title: 'Rename Stack',
            backdrop: 'static',
            keyboard: false,
            destroyOnHide: false,
            type: 'normal',
        });
        modal.body.append($("#rename-dialog .body"));
        modal.footer.append($("#rename-dialog .footer"));
        modal.show();
    });
    $('#rename-dialog button.ok').click(async function () {
        const progressIndicator = Utils.newLoadingIndicator({
            title: "Renaming Stack ...",
            subtitle: "Please wait.",
        });
        try {
            await endpoint.postAsync('stack/' + stackID, {
                title: $('#rename-dialog input[name="title"]').val(),
            });
            progressIndicator.hide();
            updateStackTitle();
            const stackConfigSearchManager = splunkjs.mvc.Components.getInstance('stack_config_search');
            stackConfigSearchManager.startSearch();
        }
        catch (err) {
            progressIndicator.hide();
            await Utils.showErrorDialog(null, err, true).wait();
        }
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
                await endpoint.delAsync('stack/' + stackID, {
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

    $("#deploy-app-button").click(function () {
        window.location.href = "app_deploy?stack=" + stackID;
    });

});