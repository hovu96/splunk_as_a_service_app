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

    // scale
    (function () {
        const statusSearchManager = splunkjs.mvc.Components.getInstance('status_search');
        const stackConfigSearchManager = splunkjs.mvc.Components.getInstance('stack_config_search');
        const scaleButton = $('#scale-button');
        // update button visivility
        const searchResults = stackConfigSearchManager.data('results', {
            output_mode: 'json',
        });
        searchResults.on("data", function () {
            if (!searchResults.hasData()) {
                return;
            }
            const settings = searchResults.data().results;
            const deploymentType = settings.find(d =>
                d.param == "deployment_type"
            );
            if (!deploymentType) {
                return;
            }
            if (deploymentType.value == "distributed") {
                scaleButton.show();
            }
            else {
                scaleButton.hide();
            }
        })
        // show dialog
        scaleButton.click(async function () {
            const progressIndicator = Utils.newLoadingIndicator({
                title: "Loading Settings ...",
                subtitle: "Please wait.",
            });
            try {
                const stackConfigResponse = await endpoint.getAsync('stack/' + stackID);
                const stackConfig = await Utils.getResponseContent(stackConfigResponse)
                console.log(stackConfig);
                progressIndicator.hide();
                const dialogBody = $(`
                <div class="form-horizontal">
                    <splunk-control-group class="" label="Number of Search Heads" help="">
                        <splunk-text-input class="option" name="search_head_count" value="${stackConfig.search_head_count}">
                        </splunk-text-input>
                    </splunk-control-group>
                    <splunk-control-group class="help" label="" help="">
                        <p>
                            Search Heads serve as a central resource for searching.
                            They replicate configurations, apps, searches, search artifacts to promote high availability.
                        </p>
                    </splunk-control-group>
                    <splunk-control-group class="" label="Number of Indexers" help="">
                        <splunk-text-input class="option" name="indexer_count" value="${stackConfig.indexer_count}">
                        </splunk-text-input>
                    </splunk-control-group>
                    <splunk-control-group class="help" label="" help="">
                        <p>
                            Indexers receive data and service search jobs coming from Search Heads.
                            Indexers replicate data, so that they maintain multiple copies of the data
                            to promote high availability and disaster recovery.
                        </p>
                    </splunk-control-group>
                </div>
                `);
                const modal = new Modal("scale-dialog", {
                    title: 'Scale Stack',
                    backdrop: 'static',
                    keyboard: false,
                    destroyOnHide: true,
                    type: 'normal',
                });
                modal.body.append(dialogBody);
                const dialogFooter = $(`
                <div class="footer">
                    <button class="btn cancel" data-dismiss="modal">Cancel</button>
                    <button class="btn btn-primary ok" data-dismiss="modal">Apply</button>
                </div>
                `)
                modal.footer.append(dialogFooter);
                // apply new settings
                $('button.ok', dialogFooter).click(async function () {
                    const indexerCount = parseInt($("splunk-text-input.option[name='indexer_count']", dialogBody).attr("value"));
                    const searchHeadCount = parseInt($("splunk-text-input.option[name='search_head_count']", dialogBody).attr("value"));
                    const progressIndicator = Utils.newLoadingIndicator({
                        title: "Updating Stack ...",
                        subtitle: "Please wait.",
                    });
                    try {
                        await endpoint.postAsync('stack/' + stackID, {
                            search_head_count: searchHeadCount,
                            indexer_count: indexerCount,
                        });
                        progressIndicator.hide();
                        statusSearchManager.startSearch();
                        stackConfigSearchManager.startSearch();
                    }
                    catch (err) {
                        progressIndicator.hide();
                        await Utils.showErrorDialog(null, err, true).wait();
                    }
                });
                modal.show();
            }
            catch (err) {
                progressIndicator.hide();
                await Utils.showErrorDialog(null, err, true).wait();
            }
        });
    })();

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